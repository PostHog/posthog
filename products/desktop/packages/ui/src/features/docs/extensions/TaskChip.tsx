import { createInlineRef } from "./inline/createInlineRef";
import { type TaskRefAttrs, taskRef } from "./inline/kinds/taskRef";

export type TaskChipAttrs = TaskRefAttrs;

export const TaskChip = createInlineRef(taskRef);
