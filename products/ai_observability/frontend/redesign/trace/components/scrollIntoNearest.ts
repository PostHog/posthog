/** A callback ref that brings its element into view when the element mounts. */
export function scrollIntoNearest(element: HTMLElement | null): void {
    element?.scrollIntoView({ block: 'nearest' })
}
