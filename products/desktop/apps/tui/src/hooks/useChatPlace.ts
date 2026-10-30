import { useState } from "react";
import { track } from "../analytics";
import { type ChatPlace, loadPrefs, savePrefs } from "../prefs";

export interface ChatPlaces {
  // Where the pane's next new chat runs.
  placeFor: (paneId: string) => ChatPlace;
  // Switches the pane, and makes the choice the saved default for panes not switched themselves.
  setPlace: (paneId: string, place: ChatPlace) => void;
}

export function useChatPlace(): ChatPlaces {
  const [places, setPlaces] = useState<Map<string, ChatPlace>>(new Map());
  const [defaultPlace, setDefaultPlace] = useState<ChatPlace>(
    () => loadPrefs().newChatPlace,
  );
  return {
    placeFor: (paneId) => places.get(paneId) ?? defaultPlace,
    setPlace: (paneId, place) => {
      track("chat place set", { place, pane_id: paneId });
      setPlaces((current) => new Map(current).set(paneId, place));
      setDefaultPlace(place);
      savePrefs({ newChatPlace: place });
    },
  };
}
