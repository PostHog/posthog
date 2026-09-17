/** Copy for the error tracking signal types, which are enum values rather than named records. */
export const ERROR_TRACKING_TYPE_COPY: Record<
  string,
  { name: string; detail: string }
> = {
  issue_created: {
    name: "New issue",
    detail: "An error that has not been seen before.",
  },
  issue_reopened: {
    name: "Issue reopened",
    detail: "A resolved issue that came back.",
  },
  issue_spiking: {
    name: "Volume spike",
    detail: "A known issue whose rate jumped above its baseline.",
  },
};
