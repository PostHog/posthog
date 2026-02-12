ISSUES_QUERY = """
query PaginatedIssues($pageSize: Int!, $cursor: String, $filter: IssueFilter) {
    issues(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            identifier
            title
            description
            priority
            priorityLabel
            estimate
            createdAt
            updatedAt
            completedAt
            canceledAt
            archivedAt
            startedAt
            dueDate
            sortOrder
            number
            url
            assignee { id name email }
            state { id name type color }
            team { id name key }
            labels { nodes { id name color } }
            project { id name }
            cycle { id name number }
            creator { id name email }
            parent { id identifier }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

PROJECTS_QUERY = """
query PaginatedProjects($pageSize: Int!, $cursor: String, $filter: ProjectFilter) {
    projects(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            name
            description
            state
            progress
            createdAt
            updatedAt
            completedAt
            canceledAt
            startedAt
            targetDate
            startDate
            slugId
            icon
            color
            url
            lead { id name email }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

TEAMS_QUERY = """
query PaginatedTeams($pageSize: Int!, $cursor: String) {
    teams(first: $pageSize, after: $cursor) {
        nodes {
            id
            name
            key
            description
            icon
            color
            createdAt
            updatedAt
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

USERS_QUERY = """
query PaginatedUsers($pageSize: Int!, $cursor: String) {
    users(first: $pageSize, after: $cursor) {
        nodes {
            id
            name
            displayName
            email
            active
            admin
            createdAt
            updatedAt
            isMe
            avatarUrl
            url
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

COMMENTS_QUERY = """
query PaginatedComments($pageSize: Int!, $cursor: String, $filter: CommentFilter) {
    comments(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            body
            createdAt
            updatedAt
            url
            issue { id identifier }
            user { id name email }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

LABELS_QUERY = """
query PaginatedLabels($pageSize: Int!, $cursor: String) {
    issueLabels(first: $pageSize, after: $cursor) {
        nodes {
            id
            name
            description
            color
            createdAt
            updatedAt
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

CYCLES_QUERY = """
query PaginatedCycles($pageSize: Int!, $cursor: String, $filter: CycleFilter) {
    cycles(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            name
            number
            description
            startsAt
            endsAt
            completedAt
            createdAt
            updatedAt
            progress
            scopeHistory
            completedScopeHistory
            team { id name }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

VIEWER_QUERY = "{ viewer { id } }"

QUERIES: dict[str, str] = {
    "issues": ISSUES_QUERY,
    "projects": PROJECTS_QUERY,
    "teams": TEAMS_QUERY,
    "users": USERS_QUERY,
    "comments": COMMENTS_QUERY,
    "labels": LABELS_QUERY,
    "cycles": CYCLES_QUERY,
}
