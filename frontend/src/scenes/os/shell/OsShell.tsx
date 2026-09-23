import { OsWindowLayer } from '../windows/OsWindowLayer'

export function OsShell(): JSX.Element {
    return (
        <div className="flex flex-col h-screen w-full bg-surface-tertiary" data-attr="os-shell">
            <OsWindowLayer />
        </div>
    )
}
