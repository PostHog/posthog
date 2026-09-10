from .. import generated_documents, logic
from . import contracts


class GeneratedKnowledgeDocumentError(Exception):
    pass


class GeneratedKnowledgeDocumentInvalidInputError(GeneratedKnowledgeDocumentError):
    pass


class GeneratedKnowledgeDocumentQuotaExceededError(GeneratedKnowledgeDocumentError):
    pass


def set_generated_knowledge_source_ready(team_id: int, *, ready: bool) -> bool:
    return generated_documents.set_generated_source_ready(team_id, ready=ready)


def create_generated_knowledge_document(
    input: contracts.CreateGeneratedKnowledgeDocument,
) -> contracts.GeneratedKnowledgeDocument:
    try:
        document, created = generated_documents.create_generated_document(input)
    except generated_documents.InvalidGeneratedKnowledgeDocument as error:
        raise GeneratedKnowledgeDocumentInvalidInputError(str(error)) from error
    except logic.QuotaExceededError as error:
        raise GeneratedKnowledgeDocumentQuotaExceededError(str(error)) from error

    return contracts.GeneratedKnowledgeDocument(
        id=document.id,
        source_id=document.source_id,
        created=created,
    )
