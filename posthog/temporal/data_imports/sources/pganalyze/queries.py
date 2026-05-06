# Matches the public GraphQL schema documented at https://pganalyze.com/docs/api/queries
SERVERS_QUERY = """
query GetServers($organizationSlug: ID!) {
    getServers(organizationSlug: $organizationSlug) {
        id
        humanId
        name
        systemType
        systemScope
        systemId
        lastSnapshotAt
    }
}
"""

ISSUES_QUERY = """
query GetIssues($serverId: ID) {
    getIssues(serverId: $serverId) {
        id
        databaseId
        description
        severity
        references {
            kind
            name
            url
            queryText
        }
    }
}
"""
