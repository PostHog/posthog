from typing import Any, Dict, List

from django.db import models
from django.utils import timezone


class UserPromptSequenceState(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="unique sequence key for user")]

    user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    key: models.CharField = models.CharField(max_length=400)

    last_updated_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    step: models.IntegerField = models.IntegerField(default=0)
    completed: models.BooleanField = models.BooleanField(default=False)
    dismissed: models.BooleanField = models.BooleanField(default=False)


prompts_config = [
    {
        "key": "session-recording-playlist-announcement",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "title": "Save your filters as playlists!",
                "text": "You can now save your search as a playlist which will keep up to date as new recordings come in matching the filters you set. Sharing with your team has never been easier!",
                "placement": "bottom-start",
                "reference": "save-recordings-playlist-button",
            }
        ],
        "rule": {"path": {"must_match": ["/recordings/recent"]}},
        "type": "one-off",
    },
]

# Return prompts
def get_active_prompt_sequences() -> List[Dict[str, Any]]:

    # we're running an experiment with a hard coded list of prompts
    return prompts_config
