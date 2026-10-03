import { describe, expect, it } from "vitest";
import {
  withYoutubeEmbedReferrer,
  YOUTUBE_EMBED_REFERRER,
} from "./youtube-embed-referrer";

describe("withYoutubeEmbedReferrer", () => {
  it("adds a Referer when the request has none", () => {
    const rewritten = withYoutubeEmbedReferrer({ Accept: "text/html" });
    expect(rewritten).toEqual({
      Accept: "text/html",
      Referer: YOUTUBE_EMBED_REFERRER,
    });
  });

  it.each([
    ["Referer", "http://localhost:5173/"],
    ["referer", "http://localhost:5173/"],
  ])(
    "keeps an existing %s header untouched",
    (headerName, existingReferrer) => {
      const rewritten = withYoutubeEmbedReferrer({
        [headerName]: existingReferrer,
      });
      expect(rewritten).toBeNull();
    },
  );
});
