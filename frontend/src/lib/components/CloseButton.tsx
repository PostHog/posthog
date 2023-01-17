import { CloseOutlined } from '@ant-design/icons'

// TODO: Remove, but de-ant PropertyFilterButton and SelectGradientOverflow first
export function CloseButton(props: Record<string, any>): JSX.Element {
    return (
        <span {...props} className={'btn-close cursor-pointer ' + (props.className ?? '')} style={{ ...props.style }}>
            <CloseOutlined />
        </span>
    )
}
