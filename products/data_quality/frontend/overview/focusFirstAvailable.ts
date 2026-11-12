export function focusFirstAvailable(elementIds: string[]): void {
    // Runs after the removed row has left the DOM, so the first id that still resolves wins.
    window.requestAnimationFrame(() => {
        for (const elementId of elementIds) {
            const element = document.getElementById(elementId)
            if (element) {
                element.focus()
                return
            }
        }
    })
}
