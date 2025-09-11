export interface TitleWithIconProps {
    icon: JSX.Element
    children: string | JSX.Element
    'data-attr'?: string
}

export function TitleWithIcon({ icon, children, 'data-attr': dataAttr }: TitleWithIconProps): JSX.Element {
    return (
        <div className="flex items-center" data-attr={dataAttr}>
            <div>{children}</div>
            <div className="ml-1.5 text-base leading-[0px]">{icon}</div>
        </div>
    )
}
