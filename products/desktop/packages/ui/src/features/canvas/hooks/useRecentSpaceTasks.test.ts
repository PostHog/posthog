import type { UserBasic } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { spacePeople } from "./useRecentSpaceTasks";

function user(name: string): UserBasic {
  return {
    id: name.length,
    uuid: `uuid-${name}`,
    first_name: name,
    last_name: "Tester",
    email: `${name}@example.com`,
  };
}

const ADA = user("ada");
const GRACE = user("grace");
const ALAN = user("alan");

describe("spacePeople", () => {
  it.each([
    {
      case: "puts the creator first even when they ran nothing",
      createdBy: ADA,
      ran: [GRACE, ALAN],
      limit: 5,
      expected: [ADA, GRACE, ALAN],
    },
    {
      case: "counts the creator once when they also ran something",
      createdBy: ADA,
      ran: [GRACE, ADA, GRACE],
      limit: 5,
      expected: [ADA, GRACE],
    },
    {
      case: "keeps the creator when the cap cuts the rest",
      createdBy: ALAN,
      ran: [ADA, GRACE],
      limit: 2,
      expected: [ALAN, ADA],
    },
    {
      case: "leads with whoever ran when the space has no creator",
      createdBy: null,
      ran: [GRACE, ADA],
      limit: 5,
      expected: [GRACE, ADA],
    },
  ])("$case", ({ createdBy, ran, limit, expected }) => {
    const tasks = ran.map((created_by) => ({ created_by }));
    expect(spacePeople(tasks, createdBy, limit)).toEqual(expected);
  });
});
