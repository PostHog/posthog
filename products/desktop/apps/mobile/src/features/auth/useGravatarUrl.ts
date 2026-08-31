import { useEffect, useState } from "react";
import { buildGravatarUrl } from "./gravatar";

export function useGravatarUrl(
  email: string | null | undefined,
  size?: number,
): string | undefined {
  const [url, setUrl] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!email) {
      setUrl(undefined);
      return;
    }
    let cancelled = false;
    setUrl(undefined);
    buildGravatarUrl(email, size)
      .then((next) => {
        if (!cancelled) setUrl(next);
      })
      .catch(() => {
        if (!cancelled) setUrl(undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [email, size]);

  return url;
}
