import { Link } from 'lib/lemon-ui/Link'

/**
 * Completion message for a synchronous export, which downloads itself the moment it finishes. The
 * browser's own download UI is easy to miss, so the toast always offers a way back to the file
 * instead of just claiming success. Built as an element rather than rendered as a component so
 * exportsLogic can hand it straight to lemonToast.
 */
export function exportCompleteToastMessage(onViewExports: () => void): JSX.Element {
    return (
        <span className="flex flex-col items-start gap-0.5">
            <span>Export complete!</span>
            <Link subtle className="text-xs" data-attr="export-complete-view-exports" onClick={onViewExports}>
                Can't find the download? View exports
            </Link>
        </span>
    )
}
