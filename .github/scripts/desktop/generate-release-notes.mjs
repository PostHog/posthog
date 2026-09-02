import { execFileSync } from "node:child_process";

const REPOSITORY = "PostHog/posthog";
const DESKTOP_LABEL = "feature/desktop";
const DESKTOP_PATH = "products/desktop/";

export function selectReleaseChanges(commits, pullRequests) {
    return commits.filter((commit) => {
        if (commit.files.some((file) => file.startsWith(DESKTOP_PATH))) {
            return true;
        }
        const pullRequest = pullRequests.get(commit.pullRequestNumber);
        return pullRequest?.labels.includes(DESKTOP_LABEL) ?? false;
    });
}

export function renderReleaseNotes(previousTag, currentTag, commits, pullRequests) {
    const lines = ["## What's Changed"];
    for (const commit of selectReleaseChanges(commits, pullRequests)) {
        const pullRequest = pullRequests.get(commit.pullRequestNumber);
        if (pullRequest) {
            lines.push(`* ${pullRequest.title} by @${pullRequest.author} in ${pullRequest.url}`);
        } else {
            lines.push(`* ${commit.subject} ([commit](https://github.com/${REPOSITORY}/commit/${commit.sha}))`);
        }
    }
    lines.push(
        "",
        `**Full Changelog**: https://github.com/${REPOSITORY}/compare/${previousTag}...${currentTag}`,
    );
    return `${lines.join("\n")}\n`;
}

function git(...args) {
    return execFileSync("git", args, { encoding: "utf8" }).trim();
}

function readCommits(previousTag, currentTag) {
    const log = git("log", "--format=%H%x09%s", `${previousTag}..${currentTag}`);
    if (!log) return [];
    return log.split("\n").map((line) => {
        const tab = line.indexOf("\t");
        const sha = line.slice(0, tab);
        const subject = line.slice(tab + 1);
        const match = subject.match(/\(#(\d+)\)$/);
        const files = git("diff-tree", "--no-commit-id", "--name-only", "-r", sha)
            .split("\n")
            .filter(Boolean);
        return {
            sha,
            subject,
            files,
            pullRequestNumber: match ? Number(match[1]) : null,
        };
    });
}

async function readPullRequests(numbers) {
    const pullRequests = new Map();
    for (let index = 0; index < numbers.length; index += 50) {
        const chunk = numbers.slice(index, index + 50);
        const fields = chunk
            .map(
                (number) => `pr${number}: pullRequest(number: ${number}) {
                    title url author { login } labels(first: 100) { nodes { name } }
                }`,
            )
            .join("\n");
        const response = await fetch("https://api.github.com/graphql", {
            method: "POST",
            headers: {
                Authorization: `Bearer ${process.env.GH_TOKEN}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ query: `query { repository(owner: "PostHog", name: "posthog") { ${fields} } }` }),
        });
        if (!response.ok) throw new Error(`GitHub GraphQL request failed: ${response.status}`);
        const payload = await response.json();
        if (payload.errors) throw new Error(`GitHub GraphQL request failed: ${JSON.stringify(payload.errors)}`);
        for (const number of chunk) {
            const pullRequest = payload.data.repository[`pr${number}`];
            if (!pullRequest) continue;
            pullRequests.set(number, {
                title: pullRequest.title,
                url: pullRequest.url,
                author: pullRequest.author?.login ?? "ghost",
                labels: pullRequest.labels.nodes.map((label) => label.name),
            });
        }
    }
    return pullRequests;
}

async function main() {
    const currentTag = process.argv[2];
    if (!currentTag) throw new Error("Usage: generate-release-notes.mjs <desktop-tag>");
    if (!process.env.GH_TOKEN) throw new Error("GH_TOKEN is required");

    const previousTag = git(
        "describe",
        "--tags",
        "--match",
        "desktop-v*",
        "--abbrev=0",
        `${currentTag}^`,
    );
    const commits = readCommits(previousTag, currentTag);
    const numbers = [...new Set(commits.map((commit) => commit.pullRequestNumber).filter(Boolean))];
    const pullRequests = await readPullRequests(numbers);
    process.stdout.write(renderReleaseNotes(previousTag, currentTag, commits, pullRequests));
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((error) => {
        console.error(error.message);
        process.exit(1);
    });
}
