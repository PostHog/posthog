import fs from "node:fs/promises";
import path from "node:path";
import type {
  FocusSessionStore,
  FocusWorktreePaths,
} from "@posthog/core/focus/host-focus";
import { focusStore } from "../../utils/store";
import { getWorktreeLocation } from "../settingsStore";

export const focusSessionStore: FocusSessionStore = {
  getSession(mainRepoPath) {
    const sessions = focusStore.get("sessions", {});
    return sessions[mainRepoPath] ?? null;
  },
  saveSession(session) {
    const sessions = focusStore.get("sessions", {});
    sessions[session.mainRepoPath] = session;
    focusStore.set("sessions", sessions);
  },
  deleteSession(mainRepoPath) {
    const sessions = focusStore.get("sessions", {});
    delete sessions[mainRepoPath];
    focusStore.set("sessions", sessions);
  },
};

export const focusWorktreePaths: FocusWorktreePaths = {
  toRelativeWorktreePath(absolutePath, mainRepoPath) {
    const repoName = path.basename(mainRepoPath);
    const worktreeName = path.basename(absolutePath);
    return `${repoName}/${worktreeName}`;
  },
  toAbsoluteWorktreePath(relativePath) {
    return path.join(getWorktreeLocation(), relativePath);
  },
  async worktreeExistsAtPath(relativePath) {
    const absolutePath = path.join(getWorktreeLocation(), relativePath);
    try {
      await fs.access(absolutePath);
      return true;
    } catch {
      return false;
    }
  },
};
