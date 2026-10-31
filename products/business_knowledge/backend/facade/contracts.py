from posthog.dataclasses import frozen


@frozen
class KnowledgeHit:
    document_title: str
    heading_path: str
    url: str
    content: str
