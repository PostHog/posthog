from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle


class KnowledgeBurstRateThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    # Same scope and rate as the default BurstRateThrottle, so personal key and session behavior
    # does not change. The default throttles do not count project secret API key requests.
    scope = "burst"
    rate = "480/minute"


class KnowledgeSustainedRateThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "sustained"
    rate = "4800/hour"


class KnowledgeProjectSecretApiKeyTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    """Caps a project's total across all of its keys, so more keys do not buy more capacity."""

    scope = "business_knowledge_psak_team_burst"
    rate = "480/minute"


class KnowledgeProjectSecretApiKeyTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "business_knowledge_psak_team_sustained"
    rate = "4800/hour"


KNOWLEDGE_THROTTLES = [
    KnowledgeBurstRateThrottle,
    KnowledgeSustainedRateThrottle,
    KnowledgeProjectSecretApiKeyTeamBurstThrottle,
    KnowledgeProjectSecretApiKeyTeamSustainedThrottle,
]
