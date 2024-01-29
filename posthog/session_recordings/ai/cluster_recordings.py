from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from pandas import DataFrame
import numpy as np
from openai import OpenAI, ChatCompletion

from types import Int, List, Any

from posthog.models import User, Team
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.schema import HogQLQuery, HogQLQueryResponse
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

# TODO: decide on the number of clusters (most likely based on number of recordings and / or some predetermining algorithm e.g Elbow point)


def perform(team_id: Int, cluster_count: Int = 15, scale_features: bool = False):
    team = Team.objects.get(team_id)

    recording_data = generate_recording_data(team=team)
    data_frame = cluster(
        columns=recording_data[0], data=recording_data[1], with_scaling=scale_features, cluster_count=cluster_count
    )
    summarize_clusters(data_frame=data_frame, cluster_count=cluster_count, sample_size=max(cluster_count / 10, 10))


def generate_recording_data(team: Team):
    q = """
        SELECT
            any(distinct_id),
            sum(active_milliseconds)/1000 as active_seconds,
            dateDiff('SECOND', min(min_first_timestamp), max(max_last_timestamp)) as duration,
            sum(click_count),
            sum(keypress_count),
            sum(mouse_activity_count),
            sum(console_log_count) as console_log_count,
            sum(console_warn_count) as console_warn_count,
            sum(console_error_count) as console_error_count
        FROM
            session_replay_events
        PREWHERE
            team_id = {team_id}
        GROUP BY
            session_id
        LIMIT
            10000
        """

    q += " order by timestamp asc"

    hq = HogQLQuery(
        query=q,
        values={
            "team_id": team.id,
        },
    )

    result: HogQLQueryResponse = HogQLQueryRunner(
        team=team,
        query=hq,
    ).calculate()

    return result.results, result.columns


def cluster(columns: List[str], results: List[List[Any]], with_scaling: bool, cluster_count: Int = 15):
    kmeans = KMeans(n_clusters=cluster_count, init="k-means++", random_state=42)
    matrix = np.array()

    df = DataFrame(results, columns=columns)

    if with_scaling:
        scaler = StandardScaler()
        matrix = scaler.fit_transform(matrix)

    kmeans.fit(matrix)
    labels = kmeans.labels_
    df["Cluster"] = labels

    return df


def summarize_clusters(df: DataFrame, cluster_count: Int, sample_size: Int):
    client = OpenAI()

    for i in range(cluster_count):
        print(f"Cluster {i} Theme:", end=" ")

        cluster_sample = df[df.Cluster == i].sample(sample_size, random_state=42)

        recording_metadata = "\n".join(cluster_sample.values)

        messages = [
            {
                "role": "system",
                "content": """
            Session Replay is PostHog's tool to record visits to web sites and apps.
            We also gather events that occur like mouse clicks and key presses.
            You write two or three sentence concise and simple summaries of those sessions based on a prompt.
            You are more likely to mention errors or things that look like business success such as checkout events.
            You don't help with other knowledge.""",
            },
            {
                "role": "user",
                "content": f"""I have a list of metadata for separate recordings on a separate line: {recording_metadata}.
            The comma separated values represent the columns: {df.columns}.
            they give an idea of what happened and when,
            if present the elements_chain extracted from the html can aid in understanding
            but should not be directly used in your response""",
            },
            {
                "role": "user",
                "content": """
            generate a two or three sentence summary of the session.
            use as concise and simple language as is possible.
            assume a reading age of around 12 years old.
            generate no text other than the summary.""",
            },
        ]

        result = client.chat.completions.create(
            model="gpt-4",  # allows 8k tokens
            temperature=0.7,
            messages=messages,
        )

        print("Title: " + result.choices[0].message.content + "\nSamples:\n")

        for j in range(sample_size):
            print(cluster_sample.Score.values[j], end="\n")

        print("-" * 100)
