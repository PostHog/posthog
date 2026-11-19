# Test file for the personal-api-key-mint semgrep rules
from posthog.accessible_teams import AccessibleTeams
from posthog.models import PersonalAPIKey
from posthog.personal_api_key_minting import mint_personal_api_key

# ruleid: personal-api-key-created-outside-mint
PersonalAPIKey.objects.create(user=user, label="key", scopes=["*"], scoped_teams=[team.id])

# ruleid: personal-api-key-created-outside-mint
PersonalAPIKey.objects.get_or_create(user=user, label="key")

# ruleid: personal-api-key-created-outside-mint
PersonalAPIKey.objects.update_or_create(user=user, label="key", defaults={"scopes": ["*"]})

# ruleid: personal-api-key-created-outside-mint
PersonalAPIKey.objects.bulk_create([PersonalAPIKey(user=user, label="key")])

# ruleid: personal-api-key-created-outside-mint
key = PersonalAPIKey(user=user, label="key")

# ruleid: personal-api-key-created-outside-mint
user.personal_api_keys.create(label="key", scopes=["*"])

# ok: personal-api-key-created-outside-mint
minted = mint_personal_api_key(user, label="key", scopes=["*"], teams=AccessibleTeams.for_user(user, [team.id]))

# ok: personal-api-key-created-outside-mint
PersonalAPIKey.objects.filter(user=user, label="key").delete()

# ok: personal-api-key-created-outside-mint
existing = PersonalAPIKey.objects.get(secure_value=secure_value)

# ruleid: accessible-teams-built-directly
teams = AccessibleTeams(user_id=user.pk, team_ids=(team.id,), _token=token)

# ok: accessible-teams-built-directly
teams = AccessibleTeams.for_user(user, [team.id])

# ok: accessible-teams-built-directly
teams = AccessibleTeams.all_for(user)
