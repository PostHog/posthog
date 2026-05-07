CUSTOMERS_QUERY = """
query PaginatedCustomers($first: Int!, $after: String, $filter: CustomersFilter) {
    customers(first: $first, after: $after, filters: $filter) {
        edges {
            node {
                id
                externalId
                fullName
                shortName
                email {
                    email
                    isVerified
                }
                status
                statusChangedAt {
                    iso8601
                }
                assignedToUser {
                    id
                    fullName
                    email
                }
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                markedAsSpamAt {
                    iso8601
                }
                markedAsSpamBy {
                    actorType
                    ... on UserActor { userId }
                }
                company {
                    id
                    name
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

THREADS_QUERY = """
query PaginatedThreads($first: Int!, $after: String, $filter: ThreadsFilter) {
    threads(first: $first, after: $after, filters: $filter) {
        edges {
            node {
                id
                externalId
                customer {
                    id
                    fullName
                    email {
                        email
                    }
                }
                title
                previewText
                priority
                status
                statusChangedAt {
                    iso8601
                }
                statusChangedBy {
                    actorType
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                assignedToUser {
                    id
                    fullName
                    email
                }
                labels {
                    id
                    labelType {
                        id
                        name
                    }
                }
                firstInboundMessageInfo {
                    timestamp {
                        iso8601
                    }
                }
                firstOutboundMessageInfo {
                    timestamp {
                        iso8601
                    }
                }
                lastInboundMessageInfo {
                    timestamp {
                        iso8601
                    }
                }
                lastOutboundMessageInfo {
                    timestamp {
                        iso8601
                    }
                }
                supportEmailAddresses
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

TIMELINE_ENTRIES_QUERY = """
query ThreadTimelineEntries($threadId: ID!, $first: Int!, $after: String) {
    thread(threadId: $threadId) {
        timelineEntries(first: $first, after: $after) {
            edges {
                node {
                    id
                    timestamp {
                        iso8601
                    }
                    actor {
                        actorType
                        ... on UserActor { userId }
                        ... on MachineUserActor { machineUserId }
                        ... on CustomerActor { customerId }
                        ... on SystemActor { systemId }
                    }
                    entry {
                        __typename
                        ... on ChatEntry {
                            chatId
                            text
                        }
                        ... on EmailEntry {
                            emailId
                            subject
                            textContent
                            to {
                                email
                                name
                            }
                            from {
                                email
                                name
                            }
                        }
                        ... on NoteEntry {
                            noteId
                            text
                        }
                        ... on CustomTimelineEntry {
                            customTimelineEntryId
                            title
                            externalId
                        }
                    }
                }
            }
            pageInfo {
                hasNextPage
                endCursor
            }
        }
    }
}"""

THREADS_LIST_QUERY = """
query ThreadIdsList($first: Int!, $after: String, $filter: ThreadsFilter) {
    threads(first: $first, after: $after, filters: $filter) {
        edges {
            node {
                id
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

VIEWER_QUERY = "{ myWorkspace { id name } }"

QUERIES: dict[str, str] = {
    "customers": CUSTOMERS_QUERY,
    "threads": THREADS_QUERY,
    "timeline_entries": TIMELINE_ENTRIES_QUERY,
}
