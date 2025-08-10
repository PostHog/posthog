from posthog.settings import get_from_env, get_list
from posthog.utils import str_to_bool
from django.conf import settings

# TRICKY: we saw unusual memory usage behavior in EU clickhouse cluster
# when allowing use of denormalized properties in some session replay event queries
# it is likely this can be returned to the default of True in future but would need careful monitoring
ALLOW_DENORMALIZED_PROPS_IN_LISTING = get_from_env("ALLOW_DENORMALIZED_PROPS_IN_LISTING", False, type_cast=str_to_bool)

# realtime snapshot loader tries REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_MAX times
# it waits for REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS between the first 3 attempts
# and REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS * 2 between the remainder
# so with the default values, it will try for 1.8 seconds before giving up (0.2, 0.2, 0.2, 0.4, 0.4, 0.4)
REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_MAX = get_from_env("REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_MAX", 6, type_cast=int)

REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS = get_from_env(
    "REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS", 0.2, type_cast=float
)

REPLAY_MESSAGE_TOO_LARGE_SAMPLE_RATE = get_from_env("REPLAY_MESSAGE_TOO_LARGE_SAMPLE_RATE", 0, type_cast=float)
REPLAY_MESSAGE_TOO_LARGE_SAMPLE_BUCKET = get_from_env(
    "REPLAY_MESSAGE_TOO_LARGE_SAMPLE_BUCKET", "posthog-cloud-prod-us-east-1-k8s-replay-samples"
)

# NB if you want to set a compression you need to install it... the producer compresses not kafka
# accepts
# * None - no compression
# * gzip - gzip compression by the kafka producer (auto decompressed by the consumer in blobby)
# * gzip-in-capture - gzip in compression in the capture service (manually decompressed by the consumer in blobby)
#
# gzip is the current default in production
# TODO we can clean this up once we've tested the new gzip-in-capture compression and don't need a setting
SESSION_RECORDING_KAFKA_COMPRESSION = get_from_env("SESSION_RECORDING_KAFKA_COMPRESSION", "gzip")

# can be used to provide an alternative script _name_ from the decide endpoint
# posthog.js will use this script name to load the rrweb script from its configured asset location
# intended to allow testing of new releases of rrweb or our lazy loaded recording script
SESSION_REPLAY_RRWEB_SCRIPT = get_from_env("SESSION_REPLAY_RRWEB_SCRIPT", None, optional=True)

# a list of teams that are allowed to use the SESSION_REPLAY_RRWEB_SCRIPT
# can be a comma separated list of team ids or '*' to allow all teams
SESSION_REPLAY_RRWEB_SCRIPT_ALLOWED_TEAMS = get_list(get_from_env("SESSION_REPLAY_RRWEB_SCRIPT_ALLOWED_TEAMS", ""))

# an AI model to use for session recording filters
SESSION_REPLAY_AI_REGEX_MODEL = get_from_env("SESSION_REPLAY_AI_REGEX_MODEL", "gpt-4.1-mini")

PLAYLIST_COUNTER_PROCESSING_SCHEDULE_SECONDS = get_from_env(
    "PLAYLIST_COUNTER_PROCESSING_SCHEDULE_SECONDS", default=60 if settings.DEBUG else 3600, type_cast=int
)

PLAYLIST_COUNTER_PROCESSING_COOLDOWN_SECONDS = get_from_env(
    "PLAYLIST_COUNTER_PROCESSING_COOLDOWN_SECONDS", 3600, type_cast=int
)

PLAYLIST_COUNTER_PROCESSING_PLAYLISTS_LIMIT = get_from_env(
    "PLAYLIST_COUNTER_PROCESSING_PLAYLISTS_LIMIT", 2500, type_cast=int
)
