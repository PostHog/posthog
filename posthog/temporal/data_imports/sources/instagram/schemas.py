from enum import StrEnum
from typing import Any

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


class InstagramResource(StrEnum):
    Users = "users"
    Media = "media"
    MediaInsights = "media_insights"
    Stories = "stories"
    StoryInsights = "story_insights"
    UserInsights = "user_insights"


ENDPOINTS = (
    InstagramResource.Users,
    InstagramResource.Media,
    InstagramResource.MediaInsights,
    InstagramResource.Stories,
    InstagramResource.StoryInsights,
    InstagramResource.UserInsights,
)

INCREMENTAL_ENDPOINTS = (InstagramResource.UserInsights,)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    InstagramResource.UserInsights: [
        {
            "label": "end_time",
            "type": IncrementalFieldType.DateTime,
            "field": "end_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}


# Fields requested for the IG Business/Creator account profile.
USERS_FIELDS = [
    "id",
    "username",
    "name",
    "biography",
    "website",
    "profile_picture_url",
    "followers_count",
    "follows_count",
    "media_count",
]

# Fields requested per media object.
MEDIA_FIELDS = [
    "id",
    "caption",
    "media_type",
    "media_product_type",
    "media_url",
    "thumbnail_url",
    "permalink",
    "timestamp",
    "username",
    "like_count",
    "comments_count",
    "is_comment_enabled",
    "owner",
    "shortcode",
]

# Fields requested per story object. Stories are a subset of media with a 24h TTL.
STORIES_FIELDS = [
    "id",
    "caption",
    "media_type",
    "media_product_type",
    "media_url",
    "thumbnail_url",
    "permalink",
    "timestamp",
    "username",
    "owner",
]

# Per-media insight metric names. Reels and feed posts share most of these;
# the Graph API silently drops unsupported metrics per media-type, so we ask
# for the union and let the API filter.
MEDIA_INSIGHTS_METRICS = [
    "impressions",
    "reach",
    "saved",
    "video_views",
    "likes",
    "comments",
    "shares",
    "total_interactions",
    "profile_visits",
    "follows",
]

# Per-story insight metric names.
STORY_INSIGHTS_METRICS = [
    "impressions",
    "reach",
    "replies",
    "exits",
    "taps_forward",
    "taps_back",
]

# Account-level daily metrics. These come from the /insights edge with period=day.
USER_INSIGHTS_METRICS = [
    "impressions",
    "reach",
    "profile_views",
    "website_clicks",
    "follower_count",
    "email_contacts",
    "phone_call_clicks",
    "text_message_clicks",
    "get_directions_clicks",
]


RESOURCE_SCHEMAS: dict[InstagramResource, dict[str, Any]] = {
    InstagramResource.Users: {
        "primary_keys": ["id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{ig_user_id}",
        "extra_params": {},
        "field_names": USERS_FIELDS,
        "partition_mode": None,
        "partition_format": None,
        "partition_keys": [],
        "kind": "single",
    },
    InstagramResource.Media: {
        "primary_keys": ["id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media",
        "extra_params": {},
        "field_names": MEDIA_FIELDS,
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["timestamp"],
        "kind": "list",
    },
    InstagramResource.Stories: {
        "primary_keys": ["id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{ig_user_id}/stories",
        "extra_params": {},
        "field_names": STORIES_FIELDS,
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["timestamp"],
        "kind": "list",
    },
    InstagramResource.MediaInsights: {
        "primary_keys": ["media_id", "name"],
        "url": "https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media",
        "extra_params": {},
        "field_names": [],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["timestamp"],
        "kind": "media_insights_fanout",
        "metrics": MEDIA_INSIGHTS_METRICS,
        "is_stats": True,
    },
    InstagramResource.StoryInsights: {
        "primary_keys": ["story_id", "name"],
        "url": "https://graph.facebook.com/{API_VERSION}/{ig_user_id}/stories",
        "extra_params": {},
        "field_names": [],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["timestamp"],
        "kind": "story_insights_fanout",
        "metrics": STORY_INSIGHTS_METRICS,
        "is_stats": True,
    },
    InstagramResource.UserInsights: {
        "primary_keys": ["ig_user_id", "name", "end_time"],
        "url": "https://graph.facebook.com/{API_VERSION}/{ig_user_id}/insights",
        "extra_params": {"period": "day"},
        "field_names": [],
        "partition_mode": "datetime",
        "partition_format": "week",
        "partition_keys": ["end_time"],
        "kind": "user_insights",
        "metrics": USER_INSIGHTS_METRICS,
        "is_stats": True,
    },
}
