import { savedDraftSchema } from "@posthog/core/offline/schemas";
import { useEffect, useRef, useState } from "react";
import { sessionIdentity } from "@/lib/auth";
import { deletePhotos, type PendingPhoto } from "@/lib/photos";
import { deviceWorkspace, WEEK } from "@/lib/storage";

interface Draft {
  text: string;
  photos: PendingPhoto[];
  taskId?: string;
}
const EMPTY: Draft = { text: "", photos: [] };

export function useDraft(id: string) {
  const identity = sessionIdentity();
  const activeKey = useRef(`${identity}/${id}`);
  activeKey.current = `${identity}/${id}`;
  const key = activeKey.current;
  const workspace = deviceWorkspace();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const current = useRef(draft);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setReady(false);
    setError(null);
    setDraft(EMPTY);
    current.current = EMPTY;
    workspace
      .read<Draft>(`draft-${id}`, WEEK)
      .then((saved) => {
        if (!active) return;
        const result = savedDraftSchema.safeParse(saved);
        if (result.success) {
          current.current = result.data;
          setDraft(result.data);
        }
      })
      .catch(() => {
        if (active) setError("Could not restore your draft.");
      })
      .finally(() => {
        if (active) setReady(true);
      });
    return () => {
      active = false;
    };
  }, [id, workspace]);

  const save = async (change: Partial<Draft>): Promise<void> => {
    if (activeKey.current !== key || sessionIdentity() !== identity)
      throw new Error("Account changed. Open the task again.");
    const next = { ...current.current, ...change };
    const removed = current.current.photos.filter(
      (photo) => !next.photos.some((item) => item.id === photo.id),
    );
    current.current = next;
    setDraft(next);
    await workspace.write(`draft-${id}`, next);
    void deletePhotos(removed);
    if (activeKey.current === key) setError(null);
  };
  const update = (
    change: Partial<Draft> | ((value: Draft) => Partial<Draft>),
  ): void => {
    void save(
      typeof change === "function" ? change(current.current) : change,
    ).catch(() =>
      setError(
        "Could not save your draft on this device. Keep this screen open.",
      ),
    );
  };
  const clear = async (): Promise<void> => {
    const photos = current.current.photos;
    if (activeKey.current === key) {
      current.current = EMPTY;
      setDraft(EMPTY);
    }
    await workspace.remove(`draft-${id}`);
    void deletePhotos(photos);
  };
  return { ...draft, ready, error, update, save, clear };
}
