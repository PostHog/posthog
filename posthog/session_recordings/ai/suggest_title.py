from posthog.models import User, Team
from posthog.utils import get_instance_region
import openai


def suggest_title(summaries: [str], user: User):
    instance_region = get_instance_region() or "HOBBY"
    messages = [
        {
            "role": "system",
            "content": """
            Session Replay is PostHog's tool to record visits to web sites and apps.
            We allow users to group recordings into playlists.
            You write concise and simple playlist titles based on prewritten summaries of sessions.
            You are more likely to mention user actions or things that look like business success such as checkout events.
            You don't help with other knowledge.""",
        },
        {
            "role": "user",
            "content": f"""the session summaries give an overview of each recording. They are on separate lines:""",
        },
    ]

    for summary in summaries:
        messages.append({"role": "user", "content": summary})

    messages.append(
        {
            "role": "user",
            "content": """
        generate a title for the playlist.
        focus on what the recordings all have in common.
        be as specific and concise as is possible.
        assume a reading age of around 12 years old.
        generate no text other than the summary.""",
        }
    )

    result = openai.ChatCompletion.create(
        # model="gpt-4-1106-preview",  # allows 128k tokens
        model="gpt-4",  # allows 8k tokens
        temperature=0.7,
        messages=messages,
        user=f"{instance_region}/{user.pk}",  # The user ID is for tracking within OpenAI in case of overuse/abuse
    )

    content: str = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"content": content}
