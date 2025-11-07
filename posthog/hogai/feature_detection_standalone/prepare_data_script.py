import json


with open("/Users/woutut/Documents/Code/posthog/playground/feature_detection/sessions_to_record_videos_full.json", "r") as f:
    sessions_data_full = json.load(f)

sessions_data = {}
for session_data in sessions_data_full["results"]:
    session_id = session_data["id"]
    session_duration = session_data["recording_duration"]
    sessions_data[session_id] = {
        "processed": False,
        "duration": session_duration,
    }

with open("/Users/woutut/Documents/Code/posthog/playground/feature_detection/sessions_to_record_videos.json", "w") as f:
    json.dump(sessions_data, f)