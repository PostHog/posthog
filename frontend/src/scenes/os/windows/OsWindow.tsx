import { osFrameName } from '../bridge/osFrame'

export interface OsWindowProps {
    id: string
    title: string
    /** A same-origin path, see `osFrameSrc`. */
    src: string
}

export function OsWindow({ id, title, src }: OsWindowProps): JSX.Element {
    return (
        <section
            className="flex flex-col flex-1 min-h-0 rounded border border-primary bg-surface-primary overflow-hidden shadow"
            aria-label={title}
            data-attr="os-window"
        >
            <header className="flex items-center h-8 px-3 shrink-0 border-b border-primary bg-surface-secondary">
                <h2 className="m-0 text-sm font-semibold truncate">{title}</h2>
            </header>
            <iframe name={osFrameName(id)} src={src} title={title} className="flex-1 w-full border-0" />
        </section>
    )
}
