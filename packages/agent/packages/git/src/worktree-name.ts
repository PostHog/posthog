import * as crypto from "node:crypto";

/**
 * Curated adjective-noun word list used to label worktrees. Words are short,
 * filesystem-safe (lowercase a-z only), and chosen to be inoffensive.
 */
// biome-ignore format: keep word lists compact
const ADJECTIVES = [
  "amber", "brave", "calm", "clever", "cosmic", "crisp", "dapper", "dusty",
  "eager", "fancy", "fluffy", "gentle", "happy", "jolly", "lively", "lucky",
  "merry", "mighty", "nimble", "plucky", "proud", "quick", "quiet", "rapid",
  "shiny", "silver", "smooth", "snappy", "spry", "sturdy", "sunny", "swift",
  "tidy", "vivid", "witty", "zesty",
];

// biome-ignore format: keep word lists compact
const NOUNS = [
  "badger", "beetle", "bison", "cedar", "comet", "cricket", "delta", "ember",
  "falcon", "ferret", "finch", "fjord", "glade", "harbor", "heron", "ibex",
  "lemur", "lynx", "marlin", "meadow", "mountain", "otter", "panda", "petal",
  "pebble", "puffin", "quokka", "raven", "river", "robin", "sparrow", "summit",
  "tiger", "valley", "willow", "wombat",
];

/**
 * Generates a short, human-readable random name (e.g. "swift-otter-42").
 * Suffix is a 2-digit number to reduce collisions while keeping names compact.
 */
export function generateHumanReadableName(): string {
  const adjective = ADJECTIVES[crypto.randomInt(0, ADJECTIVES.length)];
  const noun = NOUNS[crypto.randomInt(0, NOUNS.length)];
  const suffix = crypto.randomInt(10, 100).toString();
  return `${adjective}-${noun}-${suffix}`;
}
