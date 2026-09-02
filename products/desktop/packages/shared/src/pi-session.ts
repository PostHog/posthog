export type PiMessagingMode = "steer" | "queue";

export interface PiRuntimeHealth {
  state: "cold" | "starting" | "idle" | "streaming";
  pid?: number;
  lastUsedAt?: number;
}
