export function AbsoluteCornerBadge({
    text,
    position,
}: {
    text: string
    position: 'tl' | 'tr' | 'bl' | 'br'
}): JSX.Element {
    const displayConfig: Record<typeof position, any> = {
        tl: {
            container: 'top-0 left-0',
            badge: 'rounded-tl-lg rounded-br-lg',
            triangle: 'top-full left-0 border-l-[8px] border-l-transparent border-t-[6px] border-t-primary-3000',
        },
        tr: {
            container: 'top-0 right-0',
            badge: 'rounded-tr-lg rounded-bl-lg',
            triangle: 'top-full right-0 border-r-[8px] border-r-transparent border-t-[6px] border-t-primary-3000',
        },
        bl: {
            container: 'bottom-0 left-0',
            badge: 'rounded-bl-lg rounded-tr-lg',
            triangle: 'bottom-full left-0 border-l-[8px] border-l-transparent border-b-[6px] border-b-primary-3000',
        },
        br: {
            container: 'bottom-0 right-0',
            badge: 'rounded-br-lg rounded-tl-lg',
            triangle: 'bottom-full right-0 border-r-[8px] border-r-transparent border-b-[6px] border-b-primary-3000',
        },
    }

    return (
        <div className={`absolute z-10 ${displayConfig[position].container}`}>
            <div className="relative">
                <div
                    className={`bg-primary-3000/85 text-white text-xs font-semibold px-3 py-1 shadow-md ${displayConfig[position].badge}`}
                >
                    {text}
                </div>
                <div className={`absolute w-0 h-0 opacity-60 ${displayConfig[position].triangle}`} />
            </div>
        </div>
    )
}
