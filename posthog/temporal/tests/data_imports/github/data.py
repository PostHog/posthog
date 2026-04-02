ISSUES = [
    {
        "id": 1,
        "number": 1,
        "title": "Bug: login broken",
        "state": "open",
        "created_at": "2026-01-10T10:00:00Z",
        "updated_at": "2026-01-20T10:00:00Z",
        "user": {"id": 100, "login": "alice"},
    },
    {
        "id": 2,
        "number": 2,
        "title": "Feature: add dark mode",
        "state": "closed",
        "created_at": "2026-01-12T10:00:00Z",
        "updated_at": "2026-01-22T10:00:00Z",
        "user": {"id": 101, "login": "bob"},
    },
    {
        "id": 3,
        "number": 3,
        "title": "PR: fix typo",
        "state": "open",
        "created_at": "2026-01-14T10:00:00Z",
        "updated_at": "2026-01-24T10:00:00Z",
        "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/3"},
        "user": {"id": 102, "login": "charlie"},
    },
    {
        "id": 4,
        "number": 4,
        "title": "Issue with null PR field",
        "state": "open",
        "created_at": "2026-01-15T10:00:00Z",
        "updated_at": "2026-01-25T10:00:00Z",
        "pull_request": None,
        "user": {"id": 103, "login": "dave"},
    },
    {
        "id": 5,
        "number": 5,
        "title": "Oldest issue",
        "state": "closed",
        "created_at": "2026-01-05T10:00:00Z",
        "updated_at": "2026-01-15T10:00:00Z",
        "user": {"id": 104, "login": "eve"},
    },
]

PULL_REQUESTS = [
    {
        "id": 10,
        "number": 10,
        "title": "Fix homepage layout",
        "state": "open",
        "created_at": "2026-01-10T10:00:00Z",
        "updated_at": "2026-01-30T10:00:00Z",
        "user": {"id": 100, "login": "alice"},
    },
    {
        "id": 11,
        "number": 11,
        "title": "Add search feature",
        "state": "merged",
        "created_at": "2026-01-12T10:00:00Z",
        "updated_at": "2026-01-28T10:00:00Z",
        "user": {"id": 101, "login": "bob"},
    },
    {
        "id": 12,
        "number": 12,
        "title": "Refactor auth",
        "state": "closed",
        "created_at": "2026-01-08T10:00:00Z",
        "updated_at": "2026-01-20T10:00:00Z",
        "user": {"id": 102, "login": "charlie"},
    },
]

COMMITS = [
    {
        "sha": "abc123",
        "commit": {
            "message": "Initial commit",
            "author": {
                "name": "Alice",
                "email": "alice@example.com",
                "date": "2026-01-10T10:00:00Z",
            },
            "committer": {
                "name": "Alice",
                "email": "alice@example.com",
                "date": "2026-01-10T10:00:00Z",
            },
        },
        "author": {"id": 100, "login": "alice"},
        "committer": {"id": 100, "login": "alice"},
    },
    {
        "sha": "def456",
        "commit": {
            "message": "Add feature",
            "author": {
                "name": "Bob",
                "email": "bob@example.com",
                "date": "2026-01-15T10:00:00Z",
            },
            "committer": {
                "name": "Bob",
                "email": "bob@example.com",
                "date": "2026-01-15T10:00:00Z",
            },
        },
        "author": {"id": 101, "login": "bob"},
        "committer": {"id": 101, "login": "bob"},
    },
    {
        "sha": "ghi789",
        "commit": {
            "message": "Fix bug",
            "author": {
                "name": "Charlie",
                "email": "charlie@example.com",
                "date": "2026-01-20T10:00:00Z",
            },
            "committer": {
                "name": "Charlie",
                "email": "charlie@example.com",
                "date": "2026-01-20T10:00:00Z",
            },
        },
        "author": {"id": 102, "login": "charlie"},
        "committer": {"id": 102, "login": "charlie"},
    },
]

STARGAZERS = [
    {
        "starred_at": "2026-01-10T10:00:00Z",
        "user": {
            "id": 100,
            "login": "alice",
            "avatar_url": "https://avatars.githubusercontent.com/u/100",
            "type": "User",
        },
    },
    {
        "starred_at": "2026-01-12T10:00:00Z",
        "user": {
            "id": 101,
            "login": "bob",
            "avatar_url": "https://avatars.githubusercontent.com/u/101",
            "type": "User",
        },
    },
]
