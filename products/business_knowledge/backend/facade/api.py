from .. import generated_documents, logic
from . import contracts


class GeneratedKnowledgeDocumentError(Exception):
    """Base error for generated knowledge document writes."""


class GeneratedKnowledgeDocumentInvalidInputError(GeneratedKnowledgeDocumentError):
    """The generated document input violates the facade contract."""


class GeneratedKnowledgeDocumentQuotaExceededError(GeneratedKnowledgeDocumentError):
    """The team has no remaining Business knowledge chunk capacity."""


def set_generated_knowledge_source_ready(team_id: int, *, ready: bool) -> bool:
    return generated_documents.set_generated_source_ready(team_id, ready=ready)


def create_generated_knowledge_document(
    document_input: contracts.CreateGeneratedKnowledgeDocument,
) -> contracts.GeneratedKnowledgeDocument:
    try:
        document, created = generated_documents.create_generated_document(document_input)
    except generated_documents.InvalidGeneratedKnowledgeDocument as error:
        raise GeneratedKnowledgeDocumentInvalidInputError(str(error)) from error
    except logic.QuotaExceededError as error:
        raise GeneratedKnowledgeDocumentQuotaExceededError(str(error)) from error

    return contracts.GeneratedKnowledgeDocument(
        id=document.id,
        source_id=document.source_id,
        created=created,
    )
