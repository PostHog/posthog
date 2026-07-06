export function OrgTile({ name }: { name: string }): JSX.Element {
    return (
        <div
            className="flex items-center justify-center size-11 font-title text-xl font-extrabold text-white bg-warning border-[1.5px] border-[#a36d01] rounded-lg shadow-[0_3px_0_#a36d01]"
            aria-hidden
        >
            {(name || '?').trim().charAt(0).toUpperCase()}
        </div>
    )
}
