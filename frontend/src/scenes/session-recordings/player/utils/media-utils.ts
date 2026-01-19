export const isMediaElementPlaying = (element: HTMLMediaElement): boolean =>
    !!(element.currentTime > 0 && !element.paused && !element.ended && element.readyState > 2)
