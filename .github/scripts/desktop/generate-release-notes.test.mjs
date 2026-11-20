import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderReleaseNotes, selectReleaseChanges } from "./generate-release-notes.mjs";

const commits = [
    { sha: "desktop", subject: "fix: desktop (#1)", files: ["products/desktop/app.ts"], pullRequestNumber: 1 },
    { sha: "backend", subject: "feat: backend (#2)", files: ["posthog/api.py"], pullRequestNumber: 2 },
    { sha: "other", subject: "feat: other (#3)", files: ["frontend/index.ts"], pullRequestNumber: 3 },
    {
        sha: "codegen",
        subject: "feat: codegen (#4)",
        files: [
            "products/experiments/backend/api.py",
            "products/desktop/packages/api-client/src/generated.ts",
            "products/desktop/packages/core/src/inbox/objectKinds.generated.ts",
        ],
        pullRequestNumber: 4,
    },
];
const pullRequests = new Map([
    [1, { title: "fix: desktop", author: "one", url: "https://example.test/1", labels: [] }],
    [2, { title: "feat: retitled after merge", author: "two", url: "https://example.test/2", labels: ["feature/desktop"] }],
    [3, { title: "feat: other", author: "three", url: "https://example.test/3", labels: [] }],
    [4, { title: "feat: codegen", author: "four", url: "https://example.test/4", labels: [] }],
]);

describe("selectReleaseChanges", () => {
    it("includes desktop paths and feature/desktop labels but not generated desktop files", () => {
        assert.deepEqual(selectReleaseChanges(commits, pullRequests).map(({ sha }) => sha), ["desktop", "backend"]);
    });
});

describe("renderReleaseNotes", () => {
    it("renders only selected pull requests, by merged commit subject, and the monorepo comparison", () => {
        const notes = renderReleaseNotes("desktop-v1", "desktop-v2", commits, pullRequests);
        assert.match(notes, /^\* fix: desktop by @one in https:\/\/example\.test\/1$/m);
        assert.match(notes, /^\* feat: backend by @two in https:\/\/example\.test\/2$/m);
        assert.doesNotMatch(notes, /retitled after merge/);
        assert.doesNotMatch(notes, /feat: other/);
        assert.doesNotMatch(notes, /feat: codegen/);
        assert.match(notes, /PostHog\/posthog\/compare\/desktop-v1\.\.\.desktop-v2/);
    });
});
