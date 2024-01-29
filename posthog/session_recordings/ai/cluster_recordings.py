from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import numpy as np

from types import Int

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

# TODO: decide on the number of clusters (most likely based on number of recordings or some predetermining algorithm)


def cluster(recordings: [SessionRecording], cluster_count: Int = 100, with_scaling: bool = False):
    kmeans = KMeans(n_clusters=cluster_count, init="k-means++", random_state=42)
    matrix = np.array()

    for recording in recordings:
        session_metadata = SessionReplayEvents().get_metadata(session_id=str(recording.session_id), team=recording.team)

        if session_metadata:
            np.insert(
                matrix,
                {
                    session_metadata["active_seconds"],
                    session_metadata["click_count"],
                    session_metadata["console_error_count"],
                    session_metadata["console_log_count"],
                    session_metadata["console_warn_count"],
                    session_metadata["duration"],
                    session_metadata["keypress_count"],
                    session_metadata["mouse_activity_count"],
                },
            )

    if with_scaling:
        scaler = StandardScaler()
        matrix = scaler.fit_transform(matrix)

    kmeans.fit(matrix)

    labels = kmeans.labels_

    print(labels)
    # df["Cluster"] = labels

    # df.groupby("Cluster").Score.mean().sort_values()
