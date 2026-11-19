export function unwatchedIndicatorTooltip(otherViewersCount: number, excludedFromHideMenu: boolean): JSX.Element {
    // If person wished to be excluded from the hide recordings menu, we don't show the tooltip
    if (excludedFromHideMenu) {
        return <span>You have not watched this recording yet.</span>
    }
    if (otherViewersCount) {
        return (
            <span>
                You have not watched this recording yet. {otherViewersCount} other{' '}
                {otherViewersCount === 1 ? 'person has' : 'people have'}.
            </span>
        )
    }
    return <span>Nobody has watched this recording yet.</span>
}

export function unwatchedIndicatorAriaLabel(otherViewersCount: number, excludedFromHideMenu: boolean): string {
    return excludedFromHideMenu || otherViewersCount
        ? 'unwatched-recording-by-you-label'
        : 'unwatched-recording-by-everyone-label'
}
