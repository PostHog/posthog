import { describe, expect, it } from "vitest";
import {
  applyRenameToDetail,
  applyRenameToList,
  applyRenameToSummaries,
  getTaskSummaryTitle,
  getTaskTitle,
  rollbackDetailData,
  rollbackListData,
  rollbackSummaryData,
  shouldRollbackSessionTitle,
} from "./taskRename";

interface TestTask {
  id: string;
  title: string;
  title_manually_set?: boolean;
}

const TASK_ID = "task-1";
const OTHER_ID = "task-2";

describe("getTaskTitle / getTaskSummaryTitle", () => {
  it("finds the title by id", () => {
    const tasks: TestTask[] = [{ id: TASK_ID, title: "A" }];
    expect(getTaskTitle(tasks, TASK_ID)).toBe("A");
    expect(getTaskSummaryTitle(tasks, TASK_ID)).toBe("A");
  });

  it("returns undefined when absent", () => {
    expect(getTaskTitle(undefined, TASK_ID)).toBeUndefined();
    expect(getTaskTitle([], TASK_ID)).toBeUndefined();
  });
});

describe("applyRenameToList", () => {
  it("renames only the matching task and marks title_manually_set", () => {
    const tasks: TestTask[] = [
      { id: TASK_ID, title: "Original" },
      { id: OTHER_ID, title: "Other" },
    ];
    const next = applyRenameToList(tasks, TASK_ID, "Renamed");
    expect(next?.find((t) => t.id === TASK_ID)).toMatchObject({
      title: "Renamed",
      title_manually_set: true,
    });
    expect(next?.find((t) => t.id === OTHER_ID)).toMatchObject({
      title: "Other",
    });
  });
});

describe("applyRenameToSummaries", () => {
  it("renames only the matching summary", () => {
    const summaries = [
      { id: TASK_ID, title: "Original" },
      { id: OTHER_ID, title: "Other" },
    ];
    const next = applyRenameToSummaries(summaries, TASK_ID, "Renamed");
    expect(next?.find((s) => s.id === TASK_ID)?.title).toBe("Renamed");
    expect(next?.find((s) => s.id === OTHER_ID)?.title).toBe("Other");
  });
});

describe("applyRenameToDetail", () => {
  it("sets the new title and title_manually_set", () => {
    const detail: TestTask = { id: TASK_ID, title: "Original" };
    expect(applyRenameToDetail(detail, "Renamed")).toMatchObject({
      title: "Renamed",
      title_manually_set: true,
    });
  });
});

describe("rollbackListData", () => {
  const previous: TestTask[] = [{ id: TASK_ID, title: "Original" }];

  it("restores previous when our rename still matches", () => {
    const current: TestTask[] = [{ id: TASK_ID, title: "Renamed" }];
    expect(rollbackListData(current, previous, TASK_ID, "Renamed")).toBe(
      previous,
    );
  });

  it("keeps current when a newer rename advanced past ours", () => {
    const current: TestTask[] = [{ id: TASK_ID, title: "Second rename" }];
    expect(rollbackListData(current, previous, TASK_ID, "Renamed")).toBe(
      current,
    );
  });

  it("uses previous data when current is missing", () => {
    expect(rollbackListData(undefined, previous, TASK_ID, "Renamed")).toBe(
      previous,
    );
  });
});

describe("rollbackSummaryData", () => {
  const previous = [{ id: TASK_ID, title: "Original" }];

  it("restores previous when our rename still matches", () => {
    const current = [{ id: TASK_ID, title: "Renamed" }];
    expect(rollbackSummaryData(current, previous, TASK_ID, "Renamed")).toBe(
      previous,
    );
  });

  it("keeps current when newer rename won", () => {
    const current = [{ id: TASK_ID, title: "Second" }];
    expect(rollbackSummaryData(current, previous, TASK_ID, "Renamed")).toBe(
      current,
    );
  });
});

describe("rollbackDetailData", () => {
  const previous: TestTask = { id: TASK_ID, title: "Original" };

  it("restores previous when title still matches ours", () => {
    const current: TestTask = { id: TASK_ID, title: "Renamed" };
    expect(rollbackDetailData(current, previous, "Renamed")).toBe(previous);
  });

  it("keeps current when newer rename won", () => {
    const current: TestTask = { id: TASK_ID, title: "Second" };
    expect(rollbackDetailData(current, previous, "Renamed")).toBe(current);
  });
});

describe("shouldRollbackSessionTitle", () => {
  it("rolls back when the detail still shows our title", () => {
    expect(
      shouldRollbackSessionTitle({
        detailTitle: "Renamed",
        listTitles: [],
        newTitle: "Renamed",
      }),
    ).toBe(true);
  });

  it("rolls back when any list still shows our title", () => {
    expect(
      shouldRollbackSessionTitle({
        detailTitle: undefined,
        listTitles: [undefined, "Renamed"],
        newTitle: "Renamed",
      }),
    ).toBe(true);
  });

  it("skips rollback when a newer rename advanced past ours", () => {
    expect(
      shouldRollbackSessionTitle({
        detailTitle: "Second rename",
        listTitles: ["Second rename"],
        newTitle: "Renamed",
      }),
    ).toBe(false);
  });
});
