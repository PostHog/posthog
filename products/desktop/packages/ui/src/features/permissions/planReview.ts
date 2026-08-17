import { create } from "zustand";

export interface PlanSection {
  id: string;
  title: string;
  content: string;
}

export interface PlanReviewComment {
  id: string;
  sectionId: string;
  sectionTitle: string;
  sectionContent: string;
  text: string;
  createdAt: number;
  stale: boolean;
}

function slugify(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return slug || "plan-section";
}

function uniqueId(value: string, seen: Set<string>): string {
  const base = slugify(value);
  let id = base;
  let suffix = 2;
  while (seen.has(id)) {
    id = `${base}-${suffix}`;
    suffix += 1;
  }
  seen.add(id);
  return id;
}

export function splitPlanSections(plan: string): PlanSection[] {
  const lines = plan.split("\n");
  const starts = lines
    .map((line, index) => ({ line, index }))
    .filter(({ line }) => /^(#{1,6})\s+\S/.test(line));

  if (starts.length === 0) {
    const stepStarts = lines
      .map((line, index) => ({ line, index }))
      .filter(({ line }) => /^\s*\d+[.)]\s+\S/.test(line));
    if (stepStarts.length > 0) {
      starts.push(...stepStarts.map(({ line, index }) => ({ line, index })));
    }
  }

  if (starts.length === 0) {
    return [{ id: "plan", title: "Plan", content: plan }];
  }

  const seen = new Set<string>();
  return starts.map(({ line, index }, startIndex) => {
    const nextIndex = starts[startIndex + 1]?.index ?? lines.length;
    const title = line.replace(/^\s*(?:#{1,6}\s+|\d+[.)]\s+)/, "").trim();
    return {
      id: uniqueId(title, seen),
      title: title || "Plan section",
      content: lines.slice(index, nextIndex).join("\n").trim(),
    };
  });
}

export function buildPlanReviewFeedback(
  comments: PlanReviewComment[],
  additionalFeedback?: string,
): string {
  const activeComments = comments.filter((comment) => !comment.stale);
  const sections = activeComments
    .map(
      (comment) =>
        `- Section "${comment.sectionTitle}":\n  Context: ${comment.sectionContent}\n  Feedback: ${comment.text}`,
    )
    .join("\n\n");
  const feedback = additionalFeedback?.trim();

  return [
    "Please revise the implementation plan using this review feedback:",
    sections,
    feedback ? `Additional feedback:\n${feedback}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}

interface PlanReviewState {
  comments: Record<string, PlanReviewComment[]>;
  addComment: (
    planId: string,
    comment: Omit<PlanReviewComment, "id" | "createdAt" | "stale">,
  ) => void;
  updateComment: (
    planId: string,
    commentId: string,
    text: string,
    section?: PlanSection,
  ) => void;
  removeComment: (planId: string, commentId: string) => void;
  reconcile: (planId: string, sections: PlanSection[]) => void;
  clear: (planId: string) => void;
}

export const usePlanReviewStore = create<PlanReviewState>()((set) => ({
  comments: {},
  addComment: (planId, comment) =>
    set((state) => ({
      comments: {
        ...state.comments,
        [planId]: [
          ...(state.comments[planId] ?? []),
          {
            ...comment,
            id: crypto.randomUUID(),
            createdAt: Date.now(),
            stale: false,
          },
        ],
      },
    })),
  updateComment: (planId, commentId, text, section) =>
    set((state) => ({
      comments: {
        ...state.comments,
        [planId]: (state.comments[planId] ?? []).map((comment) =>
          comment.id === commentId
            ? {
                ...comment,
                text,
                ...(section
                  ? {
                      sectionId: section.id,
                      sectionTitle: section.title,
                      sectionContent: section.content,
                      stale: false,
                    }
                  : {}),
              }
            : comment,
        ),
      },
    })),
  removeComment: (planId, commentId) =>
    set((state) => ({
      comments: {
        ...state.comments,
        [planId]: (state.comments[planId] ?? []).filter(
          (comment) => comment.id !== commentId,
        ),
      },
    })),
  reconcile: (planId, sections) =>
    set((state) => {
      const existing = state.comments[planId];
      if (!existing) return state;
      const sectionMap = new Map(
        sections.map((section) => [section.id, section]),
      );
      const next = existing.map((comment) => {
        const section = sectionMap.get(comment.sectionId);
        return {
          ...comment,
          stale:
            !section ||
            section.content !== comment.sectionContent ||
            section.title !== comment.sectionTitle,
        };
      });
      return { comments: { ...state.comments, [planId]: next } };
    }),
  clear: (planId) =>
    set((state) => {
      const comments = { ...state.comments };
      delete comments[planId];
      return { comments };
    }),
}));
