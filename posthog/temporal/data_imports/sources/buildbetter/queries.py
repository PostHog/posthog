INTERVIEWS_QUERY = """
query PaginatedInterviews($limit: Int!, $offset: Int!, $where: interview_bool_exp) {
    interview(limit: $limit, offset: $offset, order_by: {updated_at: asc}, where: $where) {
        id
        name
        started_at
        completed_at
        created_at
        updated_at
        asset_url
        asset_duration_seconds
        type
        tags
        attendees
        monologues
        sentences
    }
}"""

EXTRACTIONS_QUERY = """
query PaginatedExtractions($limit: Int!, $offset: Int!, $where: extraction_bool_exp) {
    extraction(limit: $limit, offset: $offset, order_by: {updated_at: asc}, where: $where) {
        id
        interview_id
        summary
        context
        start_sec
        end_sec
        created_at
        updated_at
        types
        topics
        attendee
        user
    }
}"""

DOCUMENTS_QUERY = """
query PaginatedDocuments($limit: Int!, $offset: Int!, $where: document_bool_exp) {
    document(limit: $limit, offset: $offset, order_by: {updated_at: asc}, where: $where) {
        id
        name
        content
        status
        created_at
        updated_at
        creator
        template
        input_data
    }
}"""

VIEWER_QUERY = "{ interview(limit: 1) { id } }"

QUERIES: dict[str, str] = {
    "interviews": INTERVIEWS_QUERY,
    "extractions": EXTRACTIONS_QUERY,
    "documents": DOCUMENTS_QUERY,
}
