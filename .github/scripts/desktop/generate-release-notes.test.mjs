import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderReleaseNotes, selectReleaseChanges } from "./generate-release-notes.mjs";

const commits = [
    { sha: "desktop", subject: "fix: desktop", files: ["products/desktop/app.ts"], pullRequestNumber: 1 },
    { sha: "backend", subject: "feat: backend", files: ["posthog/api.py"], pullRequestNumber: 2 },
    { sha: "other", subject: "feat: other", files: ["frontend/index.ts"], pullRequestNumber: 3 },
];
const pullRequests = new Map([
    [1, { title: "fix: desktop", author: "one", url: "https://example.test/1", labels: [] }],
    [2, { title: "feat: backend", author: "two", url: "https://example.test/2", labels: ["feature/desktop"] }],
    [3, { title: "feat: other", author: "three", url: "https://example.test/3", labels: [] }],
]);

describe("selectReleaseChanges", () => {
    it("includes desktop paths and feature/desktop labels", () => {
        assert.deepEqual(selectReleaseChanges(commits, pullRequests).map(({ sha }) => sha), ["desktop", "backend"]);
    });
});

describe("renderReleaseNotes", () => {
    it("renders only selected pull requests and the monorepo comparison", () => {
        const notes = renderReleaseNotes("desktop-v1", "desktop-v2", commits, pullRequests);
        assert.match(notes, /fix: desktop by @one/);
        assert.match(notes, /feat: backend by @two/);
        assert.doesNotMatch(notes, /feat: other/);
        assert.match(notes, /PostHog\/posthog\/compare\/desktop-v1\.\.\.desktop-v2/);
    });
});
