// Loads custom icons (some icons may come from a third-party library)
import './icons.scss'

import clsx from 'clsx'
import { CSSProperties, PropsWithChildren, SVGAttributes } from 'react'

import { LemonBadge, LemonBadgeProps } from 'lib/lemon-ui/LemonBadge'

interface IconWithBadgeProps {
    content: LemonBadgeProps['content']
    status?: LemonBadgeProps['status']
    className?: string
}

interface IconWithCountProps {
    count: number
    showZero?: boolean
    status?: LemonBadgeProps['status']
    className?: string
}

export function IconWithCount({
    count,
    children,
    showZero,
    status = 'primary',
    className,
}: PropsWithChildren<IconWithCountProps>): JSX.Element {
    return (
        <span className={clsx('relative inline-flex', className)}>
            {children}
            <LemonBadge.Number count={count} size="small" position="top-right" showZero={showZero} status={status} />
        </span>
    )
}

export interface IconWithPlusProps {
    children: React.ReactNode
}

export function IconWithPlus({ children }: IconWithPlusProps): JSX.Element {
    return (
        <div className="relative">
            {children}

            <div className="absolute flex place-items-center justify-center [&_svg]:size-2.5 [&_path]:fill-[currentColor] [&_path]:stroke-[#E5E7E0] dark:[&_path]:stroke-[black] bottom-0 right-[-3px]">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path
                        d="M8 1C8.9665 1 9.75 1.7835 9.75 2.75V6.25H13.25C14.2165 6.25 15 7.0335 15 8C15 8.9665 14.2165 9.75 13.25 9.75H9.75V13.25C9.75 14.2165 8.9665 15 8 15C7.0335 15 6.25 14.2165 6.25 13.25V9.75H2.75C1.7835 9.75 1 8.9665 1 8C1 7.0335 1.7835 6.25 2.75 6.25H6.25V2.75C6.25 1.7835 7.0335 1 8 1Z"
                        fill="currentColor"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                    />
                </svg>
            </div>
        </div>
    )
}

export function IconWithBadge({
    content,
    children,
    status = 'primary',
    className,
}: PropsWithChildren<IconWithBadgeProps>): JSX.Element {
    return (
        <span className={clsx('relative inline-flex', className)}>
            {children}
            <LemonBadge visible={!!content} content={content} size="small" position="top-right" status={status} />
        </span>
    )
}

export interface LemonIconProps {
    color?: string
    fontSize?: string
    style?: CSSProperties
    className?: string
}

const LemonIconBase: React.FC<SVGAttributes<SVGSVGElement>> = ({ className, ...props }) => (
    <svg
        className={clsx('LemonIcon', className)}
        width="1em"
        height="1em"
        fill="none"
        viewBox="0 0 24 24"
        xmlns="http://www.w3.org/2000/svg"
        focusable="false"
        aria-hidden="true"
        {...props}
    />
)

// material design format-size icon
export function IconTextSize(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase fill="currentColor" {...props}>
            <path d="M2 4V7H7V19H10V7H15V4H2M21 9H12V12H15V19H18V12H21V9Z" />
        </LemonIconBase>
    )
}

// material design source-branch icon
export function IconBranch(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase fill="currentColor" {...props}>
            <path d="M13,14C9.64,14 8.54,15.35 8.18,16.24C9.25,16.7 10,17.76 10,19A3,3 0 0,1 7,22A3,3 0 0,1 4,19C4,17.69 4.83,16.58 6,16.17V7.83C4.83,7.42 4,6.31 4,5A3,3 0 0,1 7,2A3,3 0 0,1 10,5C10,6.31 9.17,7.42 8,7.83V13.12C8.88,12.47 10.16,12 12,12C14.67,12 15.56,10.66 15.85,9.77C14.77,9.32 14,8.25 14,7A3,3 0 0,1 17,4A3,3 0 0,1 20,7C20,8.34 19.12,9.5 17.91,9.86C17.65,11.29 16.68,14 13,14M7,18A1,1 0 0,0 6,19A1,1 0 0,0 7,20A1,1 0 0,0 8,19A1,1 0 0,0 7,18M7,4A1,1 0 0,0 6,5A1,1 0 0,0 7,6A1,1 0 0,0 8,5A1,1 0 0,0 7,4M17,6A1,1 0 0,0 16,7A1,1 0 0,0 17,8A1,1 0 0,0 18,7A1,1 0 0,0 17,6Z" />
        </LemonIconBase>
    )
}

// material design clipboard-edit-outline
export function IconClipboardEdit(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase fill="currentColor" {...props}>
            <path d="M21.04 12.13C21.18 12.13 21.31 12.19 21.42 12.3L22.7 13.58C22.92 13.79 22.92 14.14 22.7 14.35L21.7 15.35L19.65 13.3L20.65 12.3C20.76 12.19 20.9 12.13 21.04 12.13M19.07 13.88L21.12 15.93L15.06 22H13V19.94L19.07 13.88M11 19L9 21H5C3.9 21 3 20.1 3 19V5C3 3.9 3.9 3 5 3H9.18C9.6 1.84 10.7 1 12 1C13.3 1 14.4 1.84 14.82 3H19C20.1 3 21 3.9 21 5V9L19 11V5H17V7H7V5H5V19H11M12 3C11.45 3 11 3.45 11 4C11 4.55 11.45 5 12 5C12.55 5 13 4.55 13 4C13 3.45 12.55 3 12 3Z" />
        </LemonIconBase>
    )
}

export function IconNodeJS(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 256 282" fill="currentColor" {...props}>
            <path d="M116.504 3.58c6.962-3.985 16.03-4.003 22.986 0 34.995 19.774 70.001 39.517 104.99 59.303 6.581 3.707 10.983 11.031 10.916 18.614v118.968c.049 7.897-4.788 15.396-11.731 19.019-34.88 19.665-69.742 39.354-104.616 59.019-7.106 4.063-16.356 3.75-23.24-.646-10.457-6.062-20.932-12.094-31.39-18.15-2.137-1.274-4.546-2.288-6.055-4.36 1.334-1.798 3.719-2.022 5.657-2.807 4.365-1.388 8.374-3.616 12.384-5.778 1.014-.694 2.252-.428 3.224.193 8.942 5.127 17.805 10.403 26.777 15.481 1.914 1.105 3.852-.362 5.488-1.274 34.228-19.345 68.498-38.617 102.72-57.968 1.268-.61 1.969-1.956 1.866-3.345.024-39.245.006-78.497.012-117.742.145-1.576-.767-3.025-2.192-3.67-34.759-19.575-69.5-39.18-104.253-58.76a3.621 3.621 0 0 0-4.094-.006C91.2 39.257 56.465 58.88 21.712 78.454c-1.42.646-2.373 2.071-2.204 3.653.006 39.245 0 78.497 0 117.748a3.329 3.329 0 0 0 1.89 3.303c9.274 5.259 18.56 10.481 27.84 15.722 5.228 2.814 11.647 4.486 17.407 2.33 5.083-1.823 8.646-7.01 8.549-12.407.048-39.016-.024-78.038.036-117.048-.127-1.732 1.516-3.163 3.2-3 4.456-.03 8.918-.06 13.374.012 1.86-.042 3.14 1.823 2.91 3.568-.018 39.263.048 78.527-.03 117.79.012 10.464-4.287 21.85-13.966 26.97-11.924 6.177-26.662 4.867-38.442-1.056-10.198-5.09-19.93-11.097-29.947-16.55C5.368 215.886.555 208.357.604 200.466V81.497c-.073-7.74 4.504-15.197 11.29-18.85C46.768 42.966 81.636 23.27 116.504 3.58z" />
            <path d="M146.928 85.99c15.21-.979 31.493-.58 45.18 6.913 10.597 5.742 16.472 17.793 16.659 29.566-.296 1.588-1.956 2.464-3.472 2.355-4.413-.006-8.827.06-13.24-.03-1.872.072-2.96-1.654-3.195-3.309-1.268-5.633-4.34-11.212-9.642-13.929-8.139-4.075-17.576-3.87-26.451-3.785-6.479.344-13.446.905-18.935 4.715-4.214 2.886-5.494 8.712-3.99 13.404 1.418 3.369 5.307 4.456 8.489 5.458 18.33 4.794 37.754 4.317 55.734 10.626 7.444 2.572 14.726 7.572 17.274 15.366 3.333 10.446 1.872 22.932-5.56 31.318-6.027 6.901-14.805 10.657-23.56 12.697-11.647 2.597-23.734 2.663-35.562 1.51-11.122-1.268-22.696-4.19-31.282-11.768-7.342-6.375-10.928-16.308-10.572-25.895.085-1.619 1.697-2.748 3.248-2.615 4.444-.036 8.888-.048 13.332.006 1.775-.127 3.091 1.407 3.182 3.08.82 5.367 2.837 11 7.517 14.182 9.032 5.827 20.365 5.428 30.707 5.591 8.568-.38 18.186-.495 25.178-6.158 3.689-3.23 4.782-8.634 3.785-13.283-1.08-3.925-5.186-5.754-8.712-6.95-18.095-5.724-37.736-3.647-55.656-10.12-7.275-2.571-14.31-7.432-17.105-14.906-3.9-10.578-2.113-23.662 6.098-31.765 8.006-8.06 19.563-11.164 30.551-12.275z" />
        </LemonIconBase>
    )
}

export function IconHandClick(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 18 18" {...props}>
            <path
                d="M14.9942 7.90164C14.9942 7.82992 14.9583 7.46993 14.6342 7.10993C14.2925 6.71407 13.7524 6.49822 13.05 6.44407C12.9783 6.33579 12.8883 6.22822 12.7442 6.11993C12.3483 5.81407 11.7359 5.65164 10.9442 5.63407C10.8724 5.54407 10.7459 5.43578 10.6024 5.32822C10.2425 5.0765 9.79245 4.93236 9.23416 4.87822V3.41993C9.23416 3.27579 9.25244 2.66407 8.83831 2.23164C8.65831 2.03335 8.31659 1.79993 7.74002 1.79993C7.14587 1.79993 6.80416 2.03407 6.60587 2.23164C6.22759 2.64578 6.22759 3.18578 6.22759 3.31164V8.46C5.88587 8.1 5.50759 7.70414 5.29173 7.56C4.84173 7.21829 3.99587 7.39828 3.51002 7.75829C3.04173 8.1 2.88002 8.62243 3.06002 9.12658C3.38416 10.0266 4.19416 10.9266 4.39173 11.1424C4.57173 11.4841 5.38173 12.9782 6.10173 13.5182C6.48002 13.8065 6.76759 14.9941 6.84002 15.7499L6.87588 16.1457H13.6801V14.364C13.7701 14.1123 13.9859 13.5723 14.2201 13.3199C14.7783 12.7616 14.9583 11.3582 14.9583 10.9257V7.91986L14.9942 7.90164ZM14.1117 10.89C14.1117 11.4117 13.8959 12.4017 13.6259 12.6717C13.1576 13.14 12.87 14.04 12.8517 14.13L12.8335 14.1841V15.2283H7.68583C7.64997 15.03 7.61411 14.7783 7.54169 14.5083C7.32583 13.6441 7.03754 13.0866 6.65998 12.7983C6.13826 12.4024 5.39998 11.1241 5.16583 10.6566L5.09411 10.5484C5.09411 10.5301 4.2124 9.63008 3.90582 8.80251C3.86996 8.69423 3.86996 8.60422 3.99582 8.47836C4.22997 8.26251 4.67997 8.20836 4.78754 8.24422C5.05754 8.46008 5.88582 9.34251 6.35339 9.86422L7.12754 10.7284L7.12824 3.29418V3.25762C7.12824 3.1859 7.14652 2.95176 7.27238 2.82591C7.36238 2.71763 7.52409 2.66419 7.75824 2.66419C7.95652 2.66419 8.09995 2.71833 8.20824 2.80833C8.35238 2.97005 8.36996 3.25833 8.36996 3.36662V8.02826H9.25167V5.7599C10.0617 5.8499 10.2958 6.19161 10.3317 6.24575L10.3675 6.33575V8.02747H11.2492V6.53332C12.0051 6.60504 12.2934 6.83918 12.3651 6.94747V8.65747H13.2468V7.34332C14.021 7.4516 14.1468 7.86504 14.1651 7.95504L14.1658 10.8899L14.1117 10.89Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function SortableDragIcon(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 16 16" {...props}>
            <path
                d="M2 6C2 6.13132 2.02587 6.26136 2.07612 6.38268C2.12638 6.50401 2.20003 6.61425 2.29289 6.70711C2.38575 6.79997 2.49599 6.87362 2.61732 6.92388C2.73864 6.97413 2.86868 7 3 7C3.13132 7 3.26136 6.97413 3.38268 6.92388C3.50401 6.87362 3.61425 6.79997 3.70711 6.70711C3.79997 6.61425 3.87362 6.50401 3.92388 6.38268C3.97413 6.26136 4 6.13132 4 6C4 5.86868 3.97413 5.73864 3.92388 5.61732C3.87362 5.49599 3.79997 5.38575 3.70711 5.29289C3.61425 5.20003 3.50401 5.12638 3.38268 5.07612C3.26136 5.02587 3.13132 5 3 5C2.86868 5 2.73864 5.02587 2.61732 5.07612C2.49599 5.12638 2.38575 5.20003 2.29289 5.29289C2.20003 5.38575 2.12638 5.49599 2.07612 5.61732C2.02587 5.73864 2 5.86868 2 6ZM7 6C7 6.26522 7.10536 6.51957 7.29289 6.70711C7.48043 6.89464 7.73478 7 8 7C8.26522 7 8.51957 6.89464 8.70711 6.70711C8.89464 6.51957 9 6.26522 9 6C9 5.73478 8.89464 5.48043 8.70711 5.29289C8.51957 5.10536 8.26522 5 8 5C7.73478 5 7.48043 5.10536 7.29289 5.29289C7.10536 5.48043 7 5.73478 7 6ZM12 6C12 6.26522 12.1054 6.51957 12.2929 6.70711C12.4804 6.89464 12.7348 7 13 7C13.2652 7 13.5196 6.89464 13.7071 6.70711C13.8946 6.51957 14 6.26522 14 6C14 5.73478 13.8946 5.48043 13.7071 5.29289C13.5196 5.10536 13.2652 5 13 5C12.7348 5 12.4804 5.10536 12.2929 5.29289C12.1054 5.48043 12 5.73478 12 6Z"
                fill="currentColor"
            />
            <path
                d="M2 10C2 10.1313 2.02587 10.2614 2.07612 10.3827C2.12638 10.504 2.20003 10.6142 2.29289 10.7071C2.38575 10.8 2.49599 10.8736 2.61732 10.9239C2.73864 10.9741 2.86868 11 3 11C3.13132 11 3.26136 10.9741 3.38268 10.9239C3.50401 10.8736 3.61425 10.8 3.70711 10.7071C3.79997 10.6142 3.87362 10.504 3.92388 10.3827C3.97413 10.2614 4 10.1313 4 10C4 9.86868 3.97413 9.73864 3.92388 9.61732C3.87362 9.49599 3.79997 9.38575 3.70711 9.29289C3.61425 9.20003 3.50401 9.12638 3.38268 9.07612C3.26136 9.02587 3.13132 9 3 9C2.86868 9 2.73864 9.02587 2.61732 9.07612C2.49599 9.12638 2.38575 9.20003 2.29289 9.29289C2.20003 9.38575 2.12638 9.49599 2.07612 9.61732C2.02587 9.73864 2 9.86868 2 10ZM7 10C7 10.2652 7.10536 10.5196 7.29289 10.7071C7.48043 10.8946 7.73478 11 8 11C8.26522 11 8.51957 10.8946 8.70711 10.7071C8.89464 10.5196 9 10.2652 9 10C9 9.73478 8.89464 9.48043 8.70711 9.29289C8.51957 9.10536 8.26522 9 8 9C7.73478 9 7.48043 9.10536 7.29289 9.29289C7.10536 9.48043 7 9.73478 7 10ZM12 10C12 10.2652 12.1054 10.5196 12.2929 10.7071C12.4804 10.8946 12.7348 11 13 11C13.2652 11 13.5196 10.8946 13.7071 10.7071C13.8946 10.5196 14 10.2652 14 10C14 9.73478 13.8946 9.48043 13.7071 9.29289C13.5196 9.10536 13.2652 9 13 9C12.7348 9 12.4804 9.10536 12.2929 9.29289C12.1054 9.48043 12 9.73478 12 10Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Feedback / Announcement icon. */
export function IconFeedback(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 32 32" {...props}>
            <path
                d="M26.6667 2.66663H5.33341C3.86675 2.66663 2.68008 3.86663 2.68008 5.33329L2.66675 29.3333L8.00008 24H26.6667C28.1334 24 29.3334 22.8 29.3334 21.3333V5.33329C29.3334 3.86663 28.1334 2.66663 26.6667 2.66663ZM26.6667 21.3333H6.89341L6.10675 22.12L5.33341 22.8933V5.33329H26.6667V21.3333ZM14.6667 16H17.3334V18.6666H14.6667V16ZM14.6667 7.99996H17.3334V13.3333H14.6667V7.99996Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconSelectEvents(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M17.5 9L16.56 6.94L14.5 6L16.56 5.06L17.5 3L18.44 5.06L20.5 6L18.44 6.94L17.5 9Z"
                fill="currentColor"
            />
            <path
                d="M6 12.5L6.94 14.56L9 15.5L6.94 16.44L6 18.5L5.06 16.44L3 15.5L5.06 14.56L6 12.5Z"
                fill="currentColor"
            />
            <path d="M6 9L5.06 6.94L3 6L5.06 5.06L6 3L6.94 5.06L9 6L6.94 6.94L6 9Z" fill="currentColor" />
            <path
                d="M16.23 14.26L20 13L10 10L13 20L14.26 16.23L18.53 20.5L20.51 18.52L16.23 14.26Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Select All icon. */
export function IconSelectAll(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M3 5h2V3c-1.1 0-2 .9-2 2zm0 8h2v-2H3v2zm4 8h2v-2H7v2zM3 9h2V7H3v2zm10-6h-2v2h2V3zm6 0v2h2c0-1.1-.9-2-2-2zM5 21v-2H3c0 1.1.9 2 2 2zm-2-4h2v-2H3v2zM9 3H7v2h2V3zm2 18h2v-2h-2v2zm8-8h2v-2h-2v2zm0 8c1.1 0 2-.9 2-2h-2v2zm0-12h2V7h-2v2zm0 8h2v-2h-2v2zm-4 4h2v-2h-2v2zm0-16h2V3h-2v2zM7 17h10V7H7v10zm2-8h6v6H9V9z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Rate Review icon. */
export function IconSurveys(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17l-.59.59-.58.58V4h16v12zm-9.5-2H18v-2h-5.5zm3.86-5.87c.2-.2.2-.51 0-.71l-1.77-1.77c-.2-.2-.51-.2-.71 0L6 11.53V14h2.47l5.89-5.87z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Key icon. */
export function IconKey(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M21,10h-8.35C11.83,7.67,9.61,6,7,6c-3.31,0-6,2.69-6,6s2.69,6,6,6c2.61,0,4.83-1.67,5.65-4H13l2,2l2-2l2,2l4-4.04L21,10z M7,15c-1.65,0-3-1.35-3-3c0-1.65,1.35-3,3-3s3,1.35,3,3C10,13.65,8.65,15,7,15z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design open in app icon.*/
export function IconOpenInApp(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase aria-hidden="true" role="img" preserveAspectRatio="xMidYMid meet" {...props}>
            <path
                fill="currentColor"
                d="m12 10l-4 4h3v6h2v-6h3m3-10H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4v-2H5V8h14v10h-4v2h4a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2Z"
            />
        </LemonIconBase>
    )
}

export function IconSelectProperties(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M3.73368 17.7247H2.26243C2.10826 17.7247 1.98761 17.5981 2.00102 17.4449C2.0458 16.5963 2.29659 15.7711 2.73195 15.0397C3.16732 14.3084 3.77433 13.6926 4.50115 13.245C3.89455 12.5788 3.5259 11.6995 3.5259 10.7303C3.5259 8.66865 5.19823 7 7.25933 7C9.32043 7 10.9928 8.66865 10.9928 10.7303C10.995 11.6602 10.6471 12.5572 10.0175 13.245C11.4452 14.1243 12.4238 15.6697 12.5176 17.4449C12.5195 17.481 12.5139 17.5171 12.5012 17.551C12.4886 17.5849 12.4691 17.6158 12.444 17.642C12.4189 17.6682 12.3888 17.689 12.3553 17.7032C12.3219 17.7174 12.2859 17.7247 12.2495 17.7247H10.7783C10.6375 17.7247 10.5236 17.6148 10.5135 17.4749C10.3862 15.7929 8.97189 14.4607 7.25598 14.4607C5.54007 14.4607 4.12579 15.7929 3.99844 17.4749C3.98839 17.6148 3.87444 17.7247 3.73368 17.7247ZM8.9884 10.73C8.9884 9.77414 8.21088 8.9981 7.25574 8.9981C6.3006 8.9981 5.52308 9.77414 5.52308 10.73C5.52308 11.6859 6.3006 12.462 7.25574 12.462C8.21088 12.462 8.9884 11.6859 8.9884 10.73ZM14.8829 9.9675H21.7379C21.8819 9.9675 22 10.0436 22 10.1365V11.1508C22 11.2437 21.8819 11.3198 21.7379 11.3198H14.8829C14.7389 11.3198 14.6208 11.2437 14.6208 11.1508V10.1365C14.6208 10.0436 14.7389 9.9675 14.8829 9.9675ZM14.7057 13.0102H19.261C19.309 13.0102 19.3459 13.0863 19.3459 13.1792V14.1935C19.3459 14.2864 19.309 14.3625 19.261 14.3625H14.7057C14.6577 14.3625 14.6208 14.2864 14.6208 14.1935V13.1792C14.6208 13.0863 14.6577 13.0102 14.7057 13.0102Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Swap Horiz Less icon. */
export function IconSwapHoriz(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path d="m6.99 11-3.99 4 3.99 4v-3h7.01v-2h-7.01zm14.01-2-3.99-4v3h-7.01v2h7.01v3z" fill="currentColor" />
        </LemonIconBase>
    )
}

/** Blank space icon icon. */
export function IconBlank(props: LemonIconProps): JSX.Element {
    return <LemonIconBase fill="currentColor" {...props} />
}

/** Material Design Radio Button Unchecked icon. */
export function IconRadioButtonUnchecked(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase fill="currentColor" {...props}>
            <path d="M0 0h24v24H0z" fill="none" />
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z" />
        </LemonIconBase>
    )
}

/** Material Design Offline Bolt icon. */
export function IconOffline(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m12 2.02c-5.51 0-9.98 4.47-9.98 9.98s4.47 9.98 9.98 9.98 9.98-4.47 9.98-9.98-4.47-9.98-9.98-9.98zm0 17.96c-4.4 0-7.98-3.58-7.98-7.98s3.58-7.98 7.98-7.98 7.98 3.58 7.98 7.98-3.58 7.98-7.98 7.98zm.75-14.98-4.5 8.5h3.14v5.5l4.36-8.5h-3z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Menu icon. */
export function IconMenu(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path d="m3 18h18v-2h-18zm0-5h18v-2h-18zm0-7v2h18v-2z" fill="currentColor" />
        </LemonIconBase>
    )
}

/** Material Design Sync icon. */
export function IconSync(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m12.5 4v-3l-4 4 4 4v-3c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46c.78-1.23 1.24-2.69 1.24-4.26 0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8l-1.46-1.46c-.78 1.23-1.24 2.69-1.24 4.26 0 4.42 3.58 8 8 8v3l4-4-4-4z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Subtitles icon. */
export function IconSubtitles(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m20 4h-16c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2v-12c0-1.1-.9-2-2-2zm0 14h-16v-12h16zm-14-8h2v2h-2zm0 4h8v2h-8zm10 0h2v2h-2zm-6-4h8v2h-8z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Subtitles Off icon. */
export function IconSubtitlesOff(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <g fill="currentColor">
                <path d="m20.0001 4h-13.17002l2 2h11.17002v11.17l1.76 1.76c.15-.28.24-.59.24-.93v-12c0-1.1-.9-2-2-2z" />
                <path d="m18.0001 10h-5.17l2 2h3.17z" />
                <path d="m1.04004 3.86922 1.2 1.2c-.15.28-.24.59-.24.93v11.99998c0 1.1.9 2 2 2h13.16996l2.96 2.96 1.41-1.41-19.08996-19.09998zm2.96 2.96 3.17 3.17h-1.17v1.99998h2v-1.17l3.16996 3.17h-5.16996v2h7.16996l2 2h-11.16996z" />
            </g>
        </LemonIconBase>
    )
}

/** Material Design Calculate icon. */
export function IconCalculate(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <g fill="currentColor">
                <path d="m19 3h-14c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2v-14c0-1.1-.9-2-2-2zm0 16h-14v-14h14z" />
                <path d="m11.25 7.7207h-5v1.5h5z" />
                <path d="m18 15.75h-5v1.5h5z" />
                <path d="m18 13.25h-5v1.5h5z" />
                <path d="m8 18h1.5v-2h2v-1.5h-2v-2h-1.5v2h-2v1.5h2z" />
                <path d="m14.09 10.95 1.41-1.41 1.41 1.41 1.06-1.06-1.41-1.42 1.41-1.41-1.06-1.06-1.41 1.41-1.41-1.41-1.06 1.06 1.41 1.41-1.41 1.42z" />
            </g>
        </LemonIconBase>
    )
}

export function IconSubArrowRight(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path d="M2 0H0V10H12.01V13L16 9L12.01 5V8H2V0Z" fill="currentColor" />{' '}
        </LemonIconBase>
    )
}

export function IconGroupedEvents(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                clipRule="evenodd"
                d="m2 6h2v14h14v2h-14c-1.1 0-2-.9-2-2zm6-4h12c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2h-12c-1.1 0-2-.9-2-2v-12c0-1.1.9-2 2-2zm0 14h12v-12h-12zm4.6851-3.6586-.5398 1.6584h-1.6477l2.5106-7.27275h1.9815l2.5071 7.27275h-1.6477l-.5398-1.6584zm1.2855-3.95242-.8949 2.75212h1.8466l-.8949-2.75212z"
                fill="currentColor"
                fillRule="evenodd"
            />
        </LemonIconBase>
    )
}

export function IconCumulativeChart(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M20.8805 7.97408C15.0614 18.7809 6.51281 19.5979 2.71265 18.4578L3.28734 16.5422C6.15384 17.4021 13.7386 17.0191 19.1195 7.02588L20.8805 7.97408Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Area Chart icon. */
export function IconAreaChart(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M3 20V7l4 3 5-7 5 4h4v13Zm5-3 4-5.5 7 5.45V9h-2.7l-3.9-3.125-4.95 6.95L5 11v3.6Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Table Chart icon. */
export function IconTableChart(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M20 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h15c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 2v3H5V5h15zm-5 14h-5v-9h5v9zM5 10h3v9H5v-9zm12 9v-9h3v9h-3z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design 123 icon. */
export function Icon123(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M7,15H5.5v-4.5H4V9h3V15z M13.5,13.5h-3v-1h2c0.55,0,1-0.45,1-1V10c0-0.55-0.45-1-1-1H9v1.5h3v1h-2c-0.55,0-1,0.45-1,1V15 h4.5V13.5z M19.5,14v-4c0-0.55-0.45-1-1-1H15v1.5h3v1h-2v1h2v1h-3V15h3.5C19.05,15,19.5,14.55,19.5,14z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Groups icon. */
export function IconCohort(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m4 13c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm1.13 1.1c-.37-.06-.74-.1-1.13-.1-.99 0-1.93.21-2.78.58-.74.32-1.22 1.04-1.22 1.85v1.57h4.5v-1.61c0-.83.23-1.61.63-2.29zm14.87-1.1c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm4 3.43c0-.81-.48-1.53-1.22-1.85-.85-.37-1.79-.58-2.78-.58-.39 0-.76.04-1.13.1.4.68.63 1.46.63 2.29v1.61h4.5zm-7.76-2.78c-1.17-.52-2.61-.9-4.24-.9s-3.07.39-4.24.9c-1.08.48-1.76 1.56-1.76 2.74v1.61h12v-1.61c0-1.18-.68-2.26-1.76-2.74zm-8.17 2.35c.09-.23.13-.39.91-.69.97-.38 1.99-.56 3.02-.56s2.05.18 3.02.56c.77.3.81.46.91.69zm3.93-8c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm0-2c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Priority High icon. */
export function IconExclamation(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <g fill="currentColor">
                <path d="m12 21c1.1046 0 2-.8954 2-2s-.8954-2-2-2-2 .8954-2 2 .8954 2 2 2z" />
                <path d="m10 3h4v12h-4z" />
            </g>
        </LemonIconBase>
    )
}

/** Material Design Error Outline icon. */
export function IconErrorOutline(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m11 15h2v2h-2zm0-8h2v6h-2zm.99-5c-5.52 0-9.99 4.48-9.99 10s4.47 10 9.99 10c5.53 0 10.01-4.48 10.01-10s-4.48-10-10.01-10zm.01 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Handyman icon. */
export function IconRecording(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m10 8v8l5-4zm9-5h-14c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2v-14c0-1.1-.9-2-2-2zm0 16h-14v-14h14z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Question Answer icon. */
export function IconQuestionAnswer(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m15 4v7h-9.83l-1.17 1.17v-8.17zm1-2h-13c-.55 0-1 .45-1 1v14l4-4h10c.55 0 1-.45 1-1v-9c0-.55-.45-1-1-1zm5 4h-2v9h-13v2c0 .55.45 1 1 1h11l4 4v-15c0-.55-.45-1-1-1z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconGoogle(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M23.52 12.2727C23.52 11.4218 23.4436 10.6036 23.3018 9.81818H12V14.4654H18.4582C18.1745 15.96 17.3236 17.2254 16.0473 18.0764V21.0982H19.9418C22.2109 19.0036 23.52 15.9273 23.52 12.2727V12.2727Z"
                fill="#4285F4"
            />
            <path
                d="M12 24C15.24 24 17.9564 22.9309 19.9418 21.0982L16.0473 18.0764C14.9782 18.7964 13.6145 19.2327 12 19.2327C8.87999 19.2327 6.22908 17.1273 5.27999 14.2909H1.28726V17.3891C3.26181 21.3055 7.30908 24 12 24Z"
                fill="#34A853"
            />
            <path
                d="M5.28 14.28C5.04 13.56 4.89818 12.7964 4.89818 12C4.89818 11.2036 5.04 10.44 5.28 9.72001V6.62183H1.28727C0.469091 8.23637 0 10.0582 0 12C0 13.9418 0.469091 15.7636 1.28727 17.3782L4.39636 14.9564L5.28 14.28Z"
                fill="#FBBC05"
            />
            <path
                d="M12 4.77818C13.7673 4.77818 15.3382 5.38909 16.5927 6.56727L20.0291 3.13091C17.9454 1.18909 15.24 0 12 0C7.30908 0 3.26181 2.69455 1.28726 6.62182L5.27999 9.72C6.22908 6.88364 8.87999 4.77818 12 4.77818Z"
                fill="#EA4335"
            />
        </LemonIconBase>
    )
}

/** Material Design Open In New icon. */
export function IconOpenInNew(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m19 19h-14v-14h7v-2h-7c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2zm-5-16v2h3.59l-9.83 9.83 1.41 1.41 9.83-9.83v3.59h2v-7z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Trending Flat icon. */
export function IconTrendingFlat(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path d="m20 12-4-4v3h-12v2h12v3z" fill="currentColor" />
        </LemonIconBase>
    )
}

/** Material Design Trending Flat icon, rotated to indicate dropoff. This is different from Trending Down. */
export function IconTrendingFlatDown(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m17.6567 17.6558v-5.6568l-2.1214 2.1213-8.48523-8.48531-1.41422 1.41422 8.48525 8.48529-2.1213 2.1213z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Trending Down icon. */
export function IconTrendingDown(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m16 18 2.29-2.29-4.88-4.88-4 4-7.41-7.42 1.41-1.41 6 6 4-4 6.3 6.29 2.29-2.29v6z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Flare icon. */
export function IconFlare(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m7 11h-6v2h6zm2.17-3.24-2.12-2.12-1.41 1.41 2.12 2.12zm3.83-6.76h-2v6h2zm5.36 6.05-1.41-1.41-2.12 2.12 1.41 1.41zm-1.36 3.95v2h6v-2zm-5-2c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3zm2.83 7.24 2.12 2.12 1.41-1.41-2.12-2.12zm-9.19.71 1.41 1.41 2.12-2.12-1.41-1.41zm5.36 6.05h2v-6h-2z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

// https://pictogrammers.com/library/mdi/icon/database-edit/
export function IconQueryEditor(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M4,14V17C4,19 7.05,20.72 11,21V18.11L11.13,18C7.12,17.76 4,16.06 4,14M12,13C7.58,13 4,11.21 4,9V12C4,14.21 7.58,16 12,16C12.39,16 12.77,16 13.16,16L17,12.12C15.4,12.72 13.71,13 12,13M12,3C7.58,3 4,4.79 4,7C4,9.21 7.58,11 12,11C16.42,11 20,9.21 20,7C20,4.79 16.42,3 12,3M21,11.13C20.85,11.13 20.71,11.19 20.61,11.3L19.61,12.3L21.66,14.3L22.66,13.3C22.87,13.1 22.88,12.76 22.66,12.53L21.42,11.3C21.32,11.19 21.18,11.13 21.04,11.13M19.04,12.88L13,18.94V21H15.06L21.12,14.93L19.04,12.88Z"
            />
        </LemonIconBase>
    )
}

export function IconAction(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 20 20" {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M0 4H2V18H16V20H2C0.9 20 0 19.1 0 18V4ZM6 0H18C19.1 0 20 0.9 20 2V14C20 15.1 19.1 16 18 16H6C4.9 16 4 15.1 4 14V2C4 0.9 4.9 0 6 0ZM6 14H18V2H6V14ZM10.6851 10.3414L10.1453 11.9998H8.49756L11.0082 4.72705H12.9897L15.4968 11.9998H13.8491L13.3093 10.3414H10.6851ZM11.9706 6.38898L11.0757 9.14111H12.9223L12.0274 6.38898H11.9706Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconEvent(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 20 10" {...props}>
            <path
                d="M7.4 10.6L2.8 6L7.4 1.4L6 0L0 6L6 12L7.4 10.6ZM12.6 10.6L17.2 6L12.6 1.4L14 0L20 6L14 12L12.6 10.6Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Cancel icon. */
export function IconCancel(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m12 2c-5.53 0-10 4.47-10 10s4.47 10 10 10 10-4.47 10-10-4.47-10-10-10zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm3.59-13-3.59 3.59-3.59-3.59-1.41 1.41 3.59 3.59-3.59 3.59 1.41 1.41 3.59-3.59 3.59 3.59 1.41-1.41-3.59-3.59 3.59-3.59z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Workspace Premium icon. */
export function IconPremium(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m9.68 13.69 2.32-1.76 2.31 1.76-.88-2.85 2.32-1.84h-2.84l-.91-2.81-.91 2.81h-2.84l2.31 1.84zm10.32-3.69c0-4.42-3.58-8-8-8s-8 3.58-8 8c0 2.03.76 3.87 2 5.28v7.72l6-2 6 2v-7.72c1.24-1.41 2-3.25 2-5.28zm-8-6c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6 2.69-6 6-6zm0 15-4 1.02v-3.1c1.18.68 2.54 1.08 4 1.08s2.82-.4 4-1.08v3.1z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Play icon. */
export function IconReplay(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m12 5v-4l-5 5 5 5v-4c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6h-2c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"
                fill="currentColor"
            />{' '}
        </LemonIconBase>
    )
}

export function IconHeatmap(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase width="1em" height="1em" viewBox="0 0 32 32" {...props}>
            <path
                d="M17.5 1.49056C17.5 0.00305736 15.5844 -0.557568 14.7406 0.675557C7 11.9899 18 12.4993 18 17.9993C18 20.2262 16.1806 22.0281 13.9469 21.9987C11.7487 21.9706 10 20.1381 10 17.9399V12.5956C10 11.2393 8.34562 10.5812 7.41062 11.5643C5.7375 13.3218 4 16.3324 4 19.9993C4 26.6162 9.38312 31.9993 16 31.9993C22.6169 31.9993 28 26.6162 28 19.9993C28 9.35618 17.5 7.93681 17.5 1.49056V1.49056Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconUnverifiedEvent(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M4.8 17.4H19.2V15.6H4.8V17.4ZM6.6 21H17.4V19.2H6.6V21ZM19.2 13.8H4.8C3.81 13.8 3 12.99 3 12V4.8C3 3.81 3.81 3 4.8 3H19.2C20.19 3 21 3.81 21 4.8V12C21 12.99 20.19 13.8 19.2 13.8ZM19.2 4.8H4.8V12H19.2V4.8Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconVerifiedEvent(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M14 3H4.8C3.81 3 3 3.81 3 4.8V12C3 12.99 3.81 13.8 4.8 13.8H19.2C20.19 13.8 21 12.99 21 12V10H19.2V12H4.8V4.8H14V3ZM19.2 17.4H4.8V15.6H19.2V17.4ZM17.4 21H6.6V19.2H17.4V21Z"
                fill="currentColor"
            />
            <path
                d="M17.7289 6.04489L16.0628 4.37164L15 5.44166L17.7289 8.17774L23 2.89228L21.9372 1.82227L17.7289 6.04489Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Tune icon. */
export function IconTuning(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M3,17V19H9V17H3M3,5V7H13V5H3M13,21V19H21V17H13V15H11V21H13M7,9V11H3V13H7V15H9V9H7M21,13V11H11V13H21M15,9H17V7H21V5H17V3H15V9Z"
            />
        </LemonIconBase>
    )
}

export function IconBookmarkBorder(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="-4 -3 24 24" {...props}>
            <path
                d="M12.5 0H2.5C1.4 0 0.5 0.9 0.5 2V18L7.5 15L14.5 18V2C14.5 0.9 13.6 0 12.5 0ZM12.5 15L7.5 12.82L2.5 15V2H12.5V15Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconSlack(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 2447.6 2452.5" {...props}>
            <g clipRule="evenodd" fillRule="evenodd">
                <path
                    d="m897.4 0c-135.3.1-244.8 109.9-244.7 245.2-.1 135.3 109.5 245.1 244.8 245.2h244.8v-245.1c.1-135.3-109.5-245.1-244.9-245.3.1 0 .1 0 0 0m0 654h-652.6c-135.3.1-244.9 109.9-244.8 245.2-.2 135.3 109.4 245.1 244.7 245.3h652.7c135.3-.1 244.9-109.9 244.8-245.2.1-135.4-109.5-245.2-244.8-245.3z"
                    fill="#36c5f0"
                />
                <path
                    d="m2447.6 899.2c.1-135.3-109.5-245.1-244.8-245.2-135.3.1-244.9 109.9-244.8 245.2v245.3h244.8c135.3-.1 244.9-109.9 244.8-245.3zm-652.7 0v-654c.1-135.2-109.4-245-244.7-245.2-135.3.1-244.9 109.9-244.8 245.2v654c-.2 135.3 109.4 245.1 244.7 245.3 135.3-.1 244.9-109.9 244.8-245.3z"
                    fill="#2eb67d"
                />
                <path
                    d="m1550.1 2452.5c135.3-.1 244.9-109.9 244.8-245.2.1-135.3-109.5-245.1-244.8-245.2h-244.8v245.2c-.1 135.2 109.5 245 244.8 245.2zm0-654.1h652.7c135.3-.1 244.9-109.9 244.8-245.2.2-135.3-109.4-245.1-244.7-245.3h-652.7c-135.3.1-244.9 109.9-244.8 245.2-.1 135.4 109.4 245.2 244.7 245.3z"
                    fill="#ecb22e"
                />
                <path
                    d="m0 1553.2c-.1 135.3 109.5 245.1 244.8 245.2 135.3-.1 244.9-109.9 244.8-245.2v-245.2h-244.8c-135.3.1-244.9 109.9-244.8 245.2zm652.7 0v654c-.2 135.3 109.4 245.1 244.7 245.3 135.3-.1 244.9-109.9 244.8-245.2v-653.9c.2-135.3-109.4-245.1-244.7-245.3-135.4 0-244.9 109.8-244.8 245.1 0 0 0 .1 0 0"
                    fill="#e01e5a"
                />
            </g>
        </LemonIconBase>
    )
}

export function IconSlackExternal(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="-2 -2 24 24" {...props}>
            <g fill="currentColor" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.5">
                <path d="M13 4.75 18.25 10 13 15.25 7.75 10 13 4.75Z" />
                <path d="M8.01 5.76 7 4.75 1.75 10 7 15.25l1.01-1.01-2.872-3.037a1.75 1.75 0 0 1 0-2.406L8.01 5.76Z" />
            </g>
        </LemonIconBase>
    )
}

export function IconTwilio(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 256 256" {...props}>
            <path
                d="M128,0 C198.656,0 256,57.344 256,128 C256,198.656 198.656,256 128,256 C57.344,256 0,198.656 0,128 C0,57.344 57.344,0 128,0 Z M128,33.792 C75.776,33.792 33.792,75.776 33.792,128 C33.792,180.224 75.776,222.208 128,222.208 C180.224,222.208 222.208,180.224 222.208,128 C222.208,75.776 180.224,33.792 128,33.792 Z M159.744,133.12 C174.448029,133.12 186.368,145.039971 186.368,159.744 C186.368,174.448029 174.448029,186.368 159.744,186.368 C145.039971,186.368 133.12,174.448029 133.12,159.744 C133.12,145.039971 145.039971,133.12 159.744,133.12 Z M96.256,133.12 C110.960029,133.12 122.88,145.039971 122.88,159.744 C122.88,174.448029 110.960029,186.368 96.256,186.368 C81.5519708,186.368 69.632,174.448029 69.632,159.744 C69.632,145.039971 81.5519708,133.12 96.256,133.12 Z M159.744,69.632 C174.448029,69.632 186.368,81.5519708 186.368,96.256 C186.368,110.960029 174.448029,122.88 159.744,122.88 C145.039971,122.88 133.12,110.960029 133.12,96.256 C133.12,81.5519708 145.039971,69.632 159.744,69.632 Z M96.256,69.632 C110.960029,69.632 122.88,81.5519708 122.88,96.256 C122.88,110.960029 110.960029,122.88 96.256,122.88 C81.5519708,122.88 69.632,110.960029 69.632,96.256 C69.632,81.5519708 81.5519708,69.632 96.256,69.632 Z"
                fill="#F12E45"
            />
        </LemonIconBase>
    )
}

export function IconDatabricks(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 300 325" {...props}>
            <path
                fill="currentColor"
                d="M283.923 136.449L150.144 213.624L6.88995 131.168L0 134.982V194.844L150.144 281.115L283.923 204.234V235.926L150.144 313.1L6.88995 230.644L0 234.458V244.729L150.144 331L300 244.729V184.867L293.11 181.052L150.144 263.215L16.0766 186.334V154.643L150.144 231.524L300 145.253V86.2713L292.536 81.8697L150.144 163.739L22.9665 90.9663L150.144 17.8998L254.641 78.055L263.828 72.773V65.4371L150.144 0L0 86.2713V95.6613L150.144 181.933L283.923 104.758V136.449Z"
            />
        </LemonIconBase>
    )
}

export function IconChrome(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M12,20L15.46,14H15.45C15.79,13.4 16,12.73 16,12C16,10.8 15.46,9.73 14.62,9H19.41C19.79,9.93 20,10.94 20,12A8,8 0 0,1 12,20M4,12C4,10.54 4.39,9.18 5.07,8L8.54,14H8.55C9.24,15.19 10.5,16 12,16C12.45,16 12.88,15.91 13.29,15.77L10.89,19.91C7,19.37 4,16.04 4,12M15,12A3,3 0 0,1 12,15A3,3 0 0,1 9,12A3,3 0 0,1 12,9A3,3 0 0,1 15,12M12,4C14.96,4 17.54,5.61 18.92,8H12C10.06,8 8.45,9.38 8.08,11.21L5.7,7.08C7.16,5.21 9.44,4 12,4M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z"
            />
        </LemonIconBase>
    )
}

export function IconFirefox(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M9.27 7.94C9.27 7.94 9.27 7.94 9.27 7.94M6.85 6.74C6.86 6.74 6.86 6.74 6.85 6.74M21.28 8.6C20.85 7.55 19.96 6.42 19.27 6.06C19.83 7.17 20.16 8.28 20.29 9.1L20.29 9.12C19.16 6.3 17.24 5.16 15.67 2.68C15.59 2.56 15.5 2.43 15.43 2.3C15.39 2.23 15.36 2.16 15.32 2.09C15.26 1.96 15.2 1.83 15.17 1.69C15.17 1.68 15.16 1.67 15.15 1.67H15.13L15.12 1.67L15.12 1.67L15.12 1.67C12.9 2.97 11.97 5.26 11.74 6.71C11.05 6.75 10.37 6.92 9.75 7.22C9.63 7.27 9.58 7.41 9.62 7.53C9.67 7.67 9.83 7.74 9.96 7.68C10.5 7.42 11.1 7.27 11.7 7.23L11.75 7.23C11.83 7.22 11.92 7.22 12 7.22C12.5 7.21 12.97 7.28 13.44 7.42L13.5 7.44C13.6 7.46 13.67 7.5 13.75 7.5C13.8 7.54 13.86 7.56 13.91 7.58L14.05 7.64C14.12 7.67 14.19 7.7 14.25 7.73C14.28 7.75 14.31 7.76 14.34 7.78C14.41 7.82 14.5 7.85 14.54 7.89C14.58 7.91 14.62 7.94 14.66 7.96C15.39 8.41 16 9.03 16.41 9.77C15.88 9.4 14.92 9.03 14 9.19C17.6 11 16.63 17.19 11.64 16.95C11.2 16.94 10.76 16.85 10.34 16.7C10.24 16.67 10.14 16.63 10.05 16.58C10 16.56 9.93 16.53 9.88 16.5C8.65 15.87 7.64 14.68 7.5 13.23C7.5 13.23 8 11.5 10.83 11.5C11.14 11.5 12 10.64 12.03 10.4C12.03 10.31 10.29 9.62 9.61 8.95C9.24 8.59 9.07 8.42 8.92 8.29C8.84 8.22 8.75 8.16 8.66 8.1C8.43 7.3 8.42 6.45 8.63 5.65C7.6 6.12 6.8 6.86 6.22 7.5H6.22C5.82 7 5.85 5.35 5.87 5C5.86 5 5.57 5.16 5.54 5.18C5.19 5.43 4.86 5.71 4.56 6C4.21 6.37 3.9 6.74 3.62 7.14C3 8.05 2.5 9.09 2.28 10.18C2.28 10.19 2.18 10.59 2.11 11.1L2.08 11.33C2.06 11.5 2.04 11.65 2 11.91L2 11.94L2 12.27L2 12.32C2 17.85 6.5 22.33 12 22.33C16.97 22.33 21.08 18.74 21.88 14C21.9 13.89 21.91 13.76 21.93 13.63C22.13 11.91 21.91 10.11 21.28 8.6Z"
            />
        </LemonIconBase>
    )
}

export function IconMicrosoftEdge(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M10.86 15.37C10.17 14.6 9.7 13.68 9.55 12.65C9.25 13.11 9 13.61 8.82 14.15C7.9 16.9 9.5 20.33 12.22 21.33C14.56 22.11 17.19 20.72 18.92 19.2C19.18 18.85 21.23 17.04 20.21 16.84C17.19 18.39 13.19 17.95 10.86 15.37M11.46 9.56C12.5 9.55 11.5 9.13 11.07 8.81C10.03 8.24 8.81 7.96 7.63 7.96C3.78 8 .995 10.41 2.3 14.4C3.24 18.28 6.61 21.4 10.59 21.9C8.54 20.61 7.3 18.19 7.3 15.78C7.38 13.25 8.94 10.28 11.46 9.56M2.78 8.24C5.82 6 10.66 6.18 13.28 9C14.3 10.11 15 12 14.07 13.37C12.33 15.25 17.15 15.5 18.18 15.22C21.92 14.5 22.91 10.15 21.13 7.15C19.43 3.75 15.66 1.97 11.96 2C7.9 1.93 4.25 4.5 2.78 8.24Z"
            />
        </LemonIconBase>
    )
}

export function IconSafari(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22A10,10 0 0,1 2,12A10,10 0 0,1 12,2M12,4A8,8 0 0,0 4,12C4,14.09 4.8,16 6.11,17.41L9.88,9.88L17.41,6.11C16,4.8 14.09,4 12,4M12,20A8,8 0 0,0 20,12C20,9.91 19.2,8 17.89,6.59L14.12,14.12L6.59,17.89C8,19.2 9.91,20 12,20M12,12L11.23,11.23L9.7,14.3L12.77,12.77L12,12M12,17.5H13V19H12V17.5M15.88,15.89L16.59,15.18L17.65,16.24L16.94,16.95L15.88,15.89M17.5,12V11H19V12H17.5M12,6.5H11V5H12V6.5M8.12,8.11L7.41,8.82L6.35,7.76L7.06,7.05L8.12,8.11M6.5,12V13H5V12H6.5Z"
            />
        </LemonIconBase>
    )
}

export function IconOpera(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M9.04,17.07C8.04,15.9 7.4,14.16 7.35,12.21V11.79C7.4,9.84 8.04,8.1 9.04,6.93C9.86,5.95 10.93,5.37 12.1,5.37C14.72,5.37 16.84,8.34 16.84,12C16.84,15.66 14.72,18.63 12.1,18.63C10.93,18.63 10.33,18.5 9.04,17.07M12.03,3H12A9,9 0 0,0 3,12C3,16.83 6.8,20.77 11.57,21H12C14.3,21 16.4,20.13 18,18.71C19.84,17.06 21,14.67 21,12C21,9.33 19.84,6.94 18,5.29C16.41,3.87 14.32,3 12.03,3Z"
            />
        </LemonIconBase>
    )
}

export function IconInternetExplorer(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M13,3L14,3.06C16.8,1.79 19.23,1.64 20.5,2.92C21.5,3.93 21.58,5.67 20.92,7.72C21.61,9 22,10.45 22,12L21.95,13H9.08C9.45,15.28 11.06,17 13,17C14.31,17 15.47,16.21 16.2,15H21.5C20.25,18.5 16.92,21 13,21C11.72,21 10.5,20.73 9.41,20.25C6.5,21.68 3.89,21.9 2.57,20.56C1,18.96 1.68,15.57 4,12C4.93,10.54 6.14,9.06 7.57,7.65L8.38,6.88C7.21,7.57 5.71,8.62 4.19,10.17C5.03,6.08 8.66,3 13,3M13,7C11.21,7 9.69,8.47 9.18,10.5H16.82C16.31,8.47 14.79,7 13,7M20.06,4.06C19.4,3.39 18.22,3.35 16.74,3.81C18.22,4.5 19.5,5.56 20.41,6.89C20.73,5.65 20.64,4.65 20.06,4.06M3.89,20C4.72,20.84 6.4,20.69 8.44,19.76C6.59,18.67 5.17,16.94 4.47,14.88C3.27,17.15 3,19.07 3.89,20Z"
            />
        </LemonIconBase>
    )
}

export function IconBlackberry(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 24 24" {...props}>
            <path
                fill="currentColor"
                d="M18.13 11.8c-1.11 0-2.31 0-2.31 0l.63-2.92s1.62 0 2.22 0c1.44 0 1.78.71 1.78 1.27 0 .8-.51 1.65-2.32 1.65zm1.46 2.51c0 .8-.51 1.65-2.32 1.65-1.11 0-2.31 0-2.31 0l.63-2.92s1.62 0 2.22 0c1.44 0 1.78.71 1.78 1.27zM12.76 9.18c-1.11 0-2.31 0-2.31 0l.63-2.92s1.62 0 2.21 0c1.44 0 1.78.71 1.78 1.27 0 .8-.51 1.65-2.31 1.65zm1.52 2.75c0 .8-.51 1.65-2.32 1.65-1.11 0-2.31 0-2.31 0l.63-2.92s1.62 0 2.22 0c1.44 0 1.78.71 1.78 1.27zm-.86 4.58c0 .8-.51 1.65-2.31 1.65-1.11 0-2.31 0-2.31 0l.63-2.92s1.62 0 2.22 0c1.44 0 1.78.71 1.78 1.27zM6.59 9.18c-1.11 0-2.31 0-2.31 0l.63-2.92s1.62 0 2.22 0c1.44 0 1.78.71 1.78 1.27 0 .8-.52 1.65-2.32 1.65zm1.52 2.75c0 .8-.52 1.65-2.32 1.65-1.11 0-2.31 0-2.31 0l.63-2.92s1.63 0 2.22 0c1.44 0 1.78.71 1.78 1.27z"
            />
        </LemonIconBase>
    )
}

export function IconUCBrowser(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 24 24" {...props}>
            <circle
                cx="9.79"
                cy="17.63"
                r="3.62"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <path
                d="M14.69 19.29s2.99-.55 2.99 1.96H8.27c-3.09 0-5.6-2.51-5.6-5.6 0-1.45.55-2.77 1.46-3.77 1.75-1.92 2.55-2.6 2.55-4.19s-1.98-2.56-4.01-1.32c1.74-3.03 3.12-3.62 5.95-3.62s4.15 2.36 4.15 4.42c0 4.09-6.6 4.45-6.6 10.46"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <path
                d="M14.69 19.29c.39-.67.61-1.45.61-2.28 0-2.52-2.04-4.57-4.57-4.57-1.61 0-3.02.83-3.83 2.08M9.07 12.76c2.64-1.85 6.29-1.12 8.61 1.09 2.68-.47 3.65 1.18 3.65 1.18-1.14-.09-2.52.33-3.43.67-.59.22-1.25.07-1.67-.39-1.8-1.98-4.57-3.79-7.17-2.55z"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <path
                d="M11.49 11.79s1.39-1.43 4.49-3.09c-.12-1.5-.04-2.07.71-2.53 1.33.34 1.59 1.91 1.59 1.91 2.44.82 3.42 4.15 2.5 4.62s-3.87.13-5.68-.49"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <circle
                cx="9.79"
                cy="17.63"
                r="1.31"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </LemonIconBase>
    )
}

export function IconSamsungInternet(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 24 24" {...props}>
            <path
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.5"
                d="M8 18.93c3.83 2.21 8.72.9 10.93-2.93 2.21-3.83.9-8.72-2.93-10.93-3.83-2.21-8.72-.9-10.93 2.93-2.21 3.83-.9 8.72 2.93 10.93z"
            />
            <path
                fill="currentColor"
                fillRule="evenodd"
                d="M7.83 5.48c-2.72-.62-4.85-.36-5.57.9-1.24 2.15 2.11 6.41 7.49 9.52 5.38 3.11 10.75 3.88 12 1.73.71-1.24-.1-3.17-1.93-5.18l-.54 1.68.02.03c.61.77.96 1.44 1.12 1.94.15.51.07.72.03.78-.04.07-.18.24-.69.37-.52.12-1.27.15-2.24 0-1.94-.27-4.45-1.16-7.01-2.65-2.57-1.48-4.6-3.2-5.8-4.74-.61-.78-.97-1.44-1.12-1.95-.15-.5-.07-.71-.03-.78.04-.06.18-.24.69-.36.49-.12 1.2-.15 2.11-.03l-2.53-1.26z"
                clipRule="evenodd"
            />
        </LemonIconBase>
    )
}

export function IconFacebook(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 24 24" {...props}>
            <path
                fill="currentColor"
                d="M17 3.5a.5.5 0 00-.5-.5H14a4.77 4.77 0 00-5 4.5v2.7H6.5a.5.5 0 00-.5.5v2.6a.5.5 0 00.5.5H9v6.7a.5.5 0 00.5.5h3a.5.5 0 00.5-.5v-6.7h2.62a.5.5 0 00.49-.37l.72-2.6a.5.5 0 00-.48-.63H13V7.5a1 1 0 011-.9h2.5a.5.5 0 00.5-.5V3.5z"
            />
        </LemonIconBase>
    )
}

/** Material Web icon. */
export function IconWeb(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M16.36,14C16.44,13.34 16.5,12.68 16.5,12C16.5,11.32 16.44,10.66 16.36,10H19.74C19.9,10.64 20,11.31 20,12C20,12.69 19.9,13.36 19.74,14M14.59,19.56C15.19,18.45 15.65,17.25 15.97,16H18.92C17.96,17.65 16.43,18.93 14.59,19.56M14.34,14H9.66C9.56,13.34 9.5,12.68 9.5,12C9.5,11.32 9.56,10.65 9.66,10H14.34C14.43,10.65 14.5,11.32 14.5,12C14.5,12.68 14.43,13.34 14.34,14M12,19.96C11.17,18.76 10.5,17.43 10.09,16H13.91C13.5,17.43 12.83,18.76 12,19.96M8,8H5.08C6.03,6.34 7.57,5.06 9.4,4.44C8.8,5.55 8.35,6.75 8,8M5.08,16H8C8.35,17.25 8.8,18.45 9.4,19.56C7.57,18.93 6.03,17.65 5.08,16M4.26,14C4.1,13.36 4,12.69 4,12C4,11.31 4.1,10.64 4.26,10H7.64C7.56,10.66 7.5,11.32 7.5,12C7.5,12.68 7.56,13.34 7.64,14M12,4.03C12.83,5.23 13.5,6.57 13.91,8H10.09C10.5,6.57 11.17,5.23 12,4.03M18.92,8H15.97C15.65,6.75 15.19,5.55 14.59,4.44C16.43,5.07 17.96,6.34 18.92,8M12,2C6.47,2 2,6.5 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z"
            />
        </LemonIconBase>
    )
}

/** Material View List icon. */
export function IconListView(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M3,5v14h18V5H3z M7,7v2H5V7H7z M5,13v-2h2v2H5z M5,15h2v2H5V15z M19,17H9v-2h10V17z M19,13H9v-2h10V13z M19,9H9V7h10V9z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Grid View icon. */
export function IconGridView(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M3,3v8h8V3H3z M9,9H5V5h4V9z M3,13v8h8v-8H3z M9,19H5v-4h4V19z M13,3v8h8V3H13z M19,9h-4V5h4V9z M13,13v8h8v-8H13z M19,19h-4v-4h4V19z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Monitor icon. */
export function IconMonitor(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M21,16H3V4H21M21,2H3C1.89,2 1,2.89 1,4V16A2,2 0 0,0 3,18H10V20H8V22H16V20H14V18H21A2,2 0 0,0 23,16V4C23,2.89 22.1,2 21,2Z"
            />
        </LemonIconBase>
    )
}

/** Material Bold icon. */
export function IconBold(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M6.8 19V5H12.325C13.4083 5 14.4083 5.33333 15.325 6C16.2417 6.66667 16.7 7.59167 16.7 8.775C16.7 9.625 16.5083 10.2792 16.125 10.7375C15.7417 11.1958 15.3833 11.525 15.05 11.725C15.4667 11.9083 15.9292 12.25 16.4375 12.75C16.9458 13.25 17.2 14 17.2 15C17.2 16.4833 16.6583 17.5208 15.575 18.1125C14.4917 18.7042 13.475 19 12.525 19H6.8ZM9.825 16.2H12.425C13.225 16.2 13.7125 15.9958 13.8875 15.5875C14.0625 15.1792 14.15 14.8833 14.15 14.7C14.15 14.5167 14.0625 14.2208 13.8875 13.8125C13.7125 13.4042 13.2 13.2 12.35 13.2H9.825V16.2ZM9.825 10.5H12.15C12.7 10.5 13.1 10.3583 13.35 10.075C13.6 9.79167 13.725 9.475 13.725 9.125C13.725 8.725 13.5833 8.4 13.3 8.15C13.0167 7.9 12.65 7.775 12.2 7.775H9.825V10.5Z"
            />
        </LemonIconBase>
    )
}

/** Material Italic icon. */
export function IconItalic(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path fill="currentColor" d="M5 19V16.5H9L12 7.5H8V5H18V7.5H14.5L11.5 16.5H15V19H5Z" />
        </LemonIconBase>
    )
}

/** Material Devices icon. */
export function IconDevices(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M3 6H21V4H3C1.9 4 1 4.9 1 6V18C1 19.1 1.9 20 3 20H7V18H3V6M13 12H9V13.78C8.39 14.33 8 15.11 8 16C8 16.89 8.39 17.67 9 18.22V20H13V18.22C13.61 17.67 14 16.88 14 16S13.61 14.33 13 13.78V12M11 17.5C10.17 17.5 9.5 16.83 9.5 16S10.17 14.5 11 14.5 12.5 15.17 12.5 16 11.83 17.5 11 17.5M22 8H16C15.5 8 15 8.5 15 9V19C15 19.5 15.5 20 16 20H22C22.5 20 23 19.5 23 19V9C23 8.5 22.5 8 22 8M21 18H17V10H21V18Z"
            />
        </LemonIconBase>
    )
}

export function IconMacOS(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M18.71,19.5C17.88,20.74 17,21.95 15.66,21.97C14.32,22 13.89,21.18 12.37,21.18C10.84,21.18 10.37,21.95 9.1,22C7.79,22.05 6.8,20.68 5.96,19.47C4.25,17 2.94,12.45 4.7,9.39C5.57,7.87 7.13,6.91 8.82,6.88C10.1,6.86 11.32,7.75 12.11,7.75C12.89,7.75 14.37,6.68 15.92,6.84C16.57,6.87 18.39,7.1 19.56,8.82C19.47,8.88 17.39,10.1 17.41,12.63C17.44,15.65 20.06,16.66 20.09,16.67C20.06,16.74 19.67,18.11 18.71,19.5M13,3.5C13.73,2.67 14.94,2.04 15.94,2C16.07,3.17 15.6,4.35 14.9,5.19C14.21,6.04 13.07,6.7 11.95,6.61C11.8,5.46 12.36,4.26 13,3.5Z"
            />
        </LemonIconBase>
    )
}

export function IconAppleIOS(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M2.09 16.8H3.75V9.76H2.09M2.92 8.84C3.44 8.84 3.84 8.44 3.84 7.94C3.84 7.44 3.44 7.04 2.92 7.04C2.4 7.04 2 7.44 2 7.94C2 8.44 2.4 8.84 2.92 8.84M9.25 7.06C6.46 7.06 4.7 8.96 4.7 12C4.7 15.06 6.46 16.96 9.25 16.96C12.04 16.96 13.8 15.06 13.8 12C13.8 8.96 12.04 7.06 9.25 7.06M9.25 8.5C10.96 8.5 12.05 9.87 12.05 12C12.05 14.15 10.96 15.5 9.25 15.5C7.54 15.5 6.46 14.15 6.46 12C6.46 9.87 7.54 8.5 9.25 8.5M14.5 14.11C14.57 15.87 16 16.96 18.22 16.96C20.54 16.96 22 15.82 22 14C22 12.57 21.18 11.77 19.23 11.32L18.13 11.07C16.95 10.79 16.47 10.42 16.47 9.78C16.47 9 17.2 8.45 18.28 8.45C19.38 8.45 20.13 9 20.21 9.89H21.84C21.8 8.2 20.41 7.06 18.29 7.06C16.21 7.06 14.73 8.21 14.73 9.91C14.73 11.28 15.56 12.13 17.33 12.53L18.57 12.82C19.78 13.11 20.27 13.5 20.27 14.2C20.27 15 19.47 15.57 18.31 15.57C17.15 15.57 16.26 15 16.16 14.11H14.5Z"
            />{' '}
        </LemonIconBase>
    )
}

export function IconWindows(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M3,12V6.75L9,5.43V11.91L3,12M20,3V11.75L10,11.9V5.21L20,3M3,13L9,13.09V19.9L3,18.75V13M20,13.25V22L10,20.09V13.1L20,13.25Z"
            />{' '}
        </LemonIconBase>
    )
}

export function IconLinux(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M14.62,8.35C14.2,8.63 12.87,9.39 12.67,9.54C12.28,9.85 11.92,9.83 11.53,9.53C11.33,9.37 10,8.61 9.58,8.34C9.1,8.03 9.13,7.64 9.66,7.42C11.3,6.73 12.94,6.78 14.57,7.45C15.06,7.66 15.08,8.05 14.62,8.35M21.84,15.63C20.91,13.54 19.64,11.64 18,9.97C17.47,9.42 17.14,8.8 16.94,8.09C16.84,7.76 16.77,7.42 16.7,7.08C16.5,6.2 16.41,5.3 16,4.47C15.27,2.89 14,2.07 12.16,2C10.35,2.05 9,2.81 8.21,4.4C8,4.83 7.85,5.28 7.75,5.74C7.58,6.5 7.43,7.29 7.25,8.06C7.1,8.71 6.8,9.27 6.29,9.77C4.68,11.34 3.39,13.14 2.41,15.12C2.27,15.41 2.13,15.7 2.04,16C1.85,16.66 2.33,17.12 3.03,16.96C3.47,16.87 3.91,16.78 4.33,16.65C4.74,16.5 4.9,16.6 5,17C5.65,19.15 7.07,20.66 9.24,21.5C13.36,23.06 18.17,20.84 19.21,16.92C19.28,16.65 19.38,16.55 19.68,16.65C20.14,16.79 20.61,16.89 21.08,17C21.57,17.09 21.93,16.84 22,16.36C22.03,16.1 21.94,15.87 21.84,15.63"
            />{' '}
        </LemonIconBase>
    )
}

export function IconAndroidOS(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M16.61 15.15C16.15 15.15 15.77 14.78 15.77 14.32S16.15 13.5 16.61 13.5H16.61C17.07 13.5 17.45 13.86 17.45 14.32C17.45 14.78 17.07 15.15 16.61 15.15M7.41 15.15C6.95 15.15 6.57 14.78 6.57 14.32C6.57 13.86 6.95 13.5 7.41 13.5H7.41C7.87 13.5 8.24 13.86 8.24 14.32C8.24 14.78 7.87 15.15 7.41 15.15M16.91 10.14L18.58 7.26C18.67 7.09 18.61 6.88 18.45 6.79C18.28 6.69 18.07 6.75 18 6.92L16.29 9.83C14.95 9.22 13.5 8.9 12 8.91C10.47 8.91 9 9.24 7.73 9.82L6.04 6.91C5.95 6.74 5.74 6.68 5.57 6.78C5.4 6.87 5.35 7.08 5.44 7.25L7.1 10.13C4.25 11.69 2.29 14.58 2 18H22C21.72 14.59 19.77 11.7 16.91 10.14H16.91Z"
            />
        </LemonIconBase>
    )
}

export function IconLink(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M7.90326 16.7536C6.93594 15.7863 6.93594 14.2137 7.90326 13.2464L10.166 10.9836L9.0912 9.90883L6.82846 12.1716C5.26717 13.7329 5.26717 16.2671 6.82846 17.8284C8.38975 19.3897 10.924 19.3897 12.4853 17.8284L14.7481 15.5657L13.6733 14.4909L11.4105 16.7536C10.4432 17.7209 8.87058 17.7209 7.90326 16.7536ZM10.7883 15L15.3137 10.4745L14.1824 9.34315L9.65688 13.8686L10.7883 15ZM12.4853 6.51472L10.2226 8.77746L11.2974 9.85226L13.5601 7.58952C14.5274 6.6222 16.1 6.6222 17.0674 7.58952C18.0347 8.55684 18.0347 10.1294 17.0674 11.0968L14.8046 13.3595L15.8794 14.4343L18.1422 12.1716C19.7035 10.6103 19.7035 8.07601 18.1422 6.51472C16.5809 4.95343 14.0466 4.95343 12.4853 6.51472Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** Material Design Preview icon. */
export function IconPreview(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                fill="currentColor"
                d="M19,3H5C3.89,3,3,3.9,3,5v14c0,1.1,0.89,2,2,2h14c1.1,0,2-0.9,2-2V5C21,3.9,20.11,3,19,3z M19,19H5V7h14V19z M12,10.5 c1.84,0,3.48,0.96,4.34,2.5c-0.86,1.54-2.5,2.5-4.34,2.5S8.52,14.54,7.66,13C8.52,11.46,10.16,10.5,12,10.5 M12,9 c-2.73,0-5.06,1.66-6,4c0.94,2.34,3.27,4,6,4s5.06-1.66,6-4C17.06,10.66,14.73,9,12,9L12,9z M12,14.5c-0.83,0-1.5-0.67-1.5-1.5 s0.67-1.5,1.5-1.5s1.5,0.67,1.5,1.5S12.83,14.5,12,14.5z"
            />
        </LemonIconBase>
    )
}

export function IconEyeHidden(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M12 6.90455C15.1009 6.90455 17.8664 8.64727 19.2164 11.4045C18.7336 12.4027 18.0545 13.2618 17.2445 13.9573L18.3982 15.1109C19.5355 14.1045 20.4355 12.8445 21 11.4045C19.5845 7.81273 16.0909 5.26818 12 5.26818C10.9609 5.26818 9.96273 5.43182 9.02182 5.73455L10.3718 7.08454C10.9036 6.97818 11.4436 6.90455 12 6.90455ZM11.1245 7.83727L12.8182 9.53091C13.2845 9.73545 13.6609 10.1118 13.8655 10.5782L15.5591 12.2718C15.6245 11.9936 15.6736 11.6991 15.6736 11.3964C15.6818 9.36727 14.0291 7.72273 12 7.72273C11.6973 7.72273 11.4109 7.76364 11.1245 7.83727ZM3.82636 5.16182L6.01909 7.35455C4.68545 8.40182 3.63 9.79273 3 11.4045C4.41545 14.9964 7.90909 17.5409 12 17.5409C13.2436 17.5409 14.4382 17.3036 15.5345 16.87L18.3327 19.6682L19.4864 18.5145L4.98 4L3.82636 5.16182ZM9.96273 11.2982L12.0982 13.4336C12.0655 13.4418 12.0327 13.45 12 13.45C10.8709 13.45 9.95455 12.5336 9.95455 11.4045C9.95455 11.3636 9.96273 11.3391 9.96273 11.2982ZM7.18091 8.51636L8.61273 9.94818C8.42455 10.3982 8.31818 10.8891 8.31818 11.4045C8.31818 13.4336 9.97091 15.0864 12 15.0864C12.5155 15.0864 13.0064 14.98 13.4482 14.7918L14.25 15.5936C13.53 15.79 12.7773 15.9045 12 15.9045C8.89909 15.9045 6.13364 14.1618 4.78364 11.4045C5.35636 10.2345 6.19091 9.26909 7.18091 8.51636Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconFunnelHorizontal(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M19 5L19 8L5 8L5 5L19 5ZM15 10.6L15 13.4L5 13.4L5 10.6L15 10.6ZM11 16.2L11 19L5 19L5 16.2L11 16.2Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconArrowUp(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path d="M4 12l1.41 1.41L11 7.83V20h2V7.83l5.58 5.59L20 12l-8-8-8 8z" fill="currentColor" />
        </LemonIconBase>
    )
}

export function IconArrowDown(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path d="M20 12l-1.41-1.41L13 16.17V4h-2v12.17l-5.58-5.59L4 12l8 8 8-8z" fill="currentColor" />
        </LemonIconBase>
    )
}

export function IconFunnelVertical(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path d="M5 5H8V19H5V5ZM10.6 9H13.4V19H10.6V9ZM16.2 13H19V19H16.2V13Z" fill="currentColor" />
        </LemonIconBase>
    )
}

export function IconFullScreen(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path d="M5 14H3V20H10V18H5V14Z" fill="currentColor" />
            <path d="M10 6L10 4L3 4L3 10L5 10L5 6L10 6Z" fill="currentColor" />
            <path d="M19 14H21V20H14V18H19V14Z" fill="currentColor" />
            <path d="M14 6L14 4L21 4L21 10L19 10L19 6L14 6Z" fill="currentColor" />
        </LemonIconBase>
    )
}

export function IconPlayCircle(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 20C7.59 20 4 16.41 4 12C4 7.59 7.59 4 12 4C16.41 4 20 7.59 20 12C20 16.41 16.41 20 12 20ZM9.5 16.5L16.5 12L9.5 7.5V16.5Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconSkipBackward(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M21.8636 13.6486C22.7745 8.20179 18.9753 3.03539 13.3613 2.08842C10.1083 1.5397 6.96075 2.53504 4.71122 4.52864L3.64727 3.39843C3.52963 3.27464 3.31814 3.33531 3.29323 3.49844L2.61914 7.61871C2.59751 7.7469 2.70624 7.86158 2.83872 7.85097L7.12768 7.57298C7.16635 7.57046 7.20339 7.55738 7.23454 7.53524C7.26569 7.5131 7.28969 7.48281 7.30378 7.44784C7.31787 7.41288 7.32148 7.37466 7.31418 7.33758C7.30689 7.3005 7.289 7.26607 7.26256 7.23825L6.10772 6.01158C6.35345 5.79443 6.6153 5.59014 6.89033 5.40074C7.75239 4.80488 8.72707 4.3786 9.7602 4.14561C10.831 3.90282 11.9307 3.87537 13.0286 4.06056C14.1265 4.24575 15.1564 4.63245 16.0883 5.21303C16.9896 5.77326 17.7628 6.48932 18.3877 7.34012C19.0126 8.19091 19.4575 9.13303 19.7082 10.1413C19.9684 11.1866 20.0076 12.2555 19.828 13.3205C19.6483 14.3854 19.2606 15.3823 18.6724 16.282C18.1048 17.1522 17.3755 17.8963 16.5061 18.495C15.6366 19.0938 14.6714 19.5166 13.6362 19.7502C12.5654 19.993 11.4657 20.0204 10.3678 19.8352C9.26987 19.65 8.23995 19.2633 7.30808 18.6827C6.40854 18.1237 5.62762 17.4013 5.00872 16.5557C4.8493 16.3386 4.70383 16.1163 4.56724 15.8879C4.54048 15.8423 4.49636 15.8085 4.44446 15.7941C4.39256 15.7796 4.3371 15.7856 4.29013 15.8108L2.84288 16.5656C2.74229 16.6196 2.70583 16.7427 2.76244 16.841C4.25318 19.3768 6.85284 21.2731 10.0347 21.8098C15.6538 22.7576 20.9514 19.1029 21.8636 13.6486Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/* Material design robot-outline icon https://pictogrammers.com/library/mdi/icon/robot-outline */
export function IconRobot(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props} fill="currentColor">
            <path d="M17.5 15.5C17.5 16.61 16.61 17.5 15.5 17.5S13.5 16.61 13.5 15.5 14.4 13.5 15.5 13.5 17.5 14.4 17.5 15.5M8.5 13.5C7.4 13.5 6.5 14.4 6.5 15.5S7.4 17.5 8.5 17.5 10.5 16.61 10.5 15.5 9.61 13.5 8.5 13.5M23 15V18C23 18.55 22.55 19 22 19H21V20C21 21.11 20.11 22 19 22H5C3.9 22 3 21.11 3 20V19H2C1.45 19 1 18.55 1 18V15C1 14.45 1.45 14 2 14H3C3 10.13 6.13 7 10 7H11V5.73C10.4 5.39 10 4.74 10 4C10 2.9 10.9 2 12 2S14 2.9 14 4C14 4.74 13.6 5.39 13 5.73V7H14C17.87 7 21 10.13 21 14H22C22.55 14 23 14.45 23 15M21 16H19V14C19 11.24 16.76 9 14 9H10C7.24 9 5 11.24 5 14V16H3V17H5V20H19V17H21V16Z" />
        </LemonIconBase>
    )
}
export function IconDragHandle(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="m11 18c0 1.1-.9 2-2 2s-2-.9-2-2 .9-2 2-2 2 .9 2 2zm-2-8c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0-6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm6 4c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconDocumentExpand({ mode, ...props }: LemonIconProps & { mode: 'expand' | 'collapse' }): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M3 2.58828C3 2.26328 3.26328 2 3.58828 2C3.91328 2 4.17656 2.26328 4.17656 2.58828V21.4117C4.17656 21.7367 3.91328 22 3.58828 22C3.26328 22 3 21.7367 3 21.4117V2.58828ZM19.4704 2.58828C19.4704 2.26328 19.7337 2 20.0587 2C20.3837 2 20.6469 2.26328 20.6469 2.58828V21.4117C20.6469 21.7367 20.3837 22 20.0587 22C19.7337 22 19.4704 21.7367 19.4704 21.4117V2.58828ZM7.1172 13.1765C6.79298 13.1765 6.5297 12.9132 6.5297 12.5882C6.5297 12.2632 6.79298 11.9999 7.1172 11.9999H16.5296C16.8538 11.9999 17.1171 12.2632 17.1171 12.5882C17.1171 12.9132 16.8538 13.1765 16.5296 13.1765H7.1172ZM7.1172 16.1179C6.79298 16.1179 6.5297 15.8538 6.5297 15.5296C6.5297 15.2046 6.79298 14.9413 7.1172 14.9413H16.5296C16.8538 14.9413 17.1171 15.2046 17.1171 15.5296C17.1171 15.8538 16.8538 16.1179 16.5296 16.1179H7.1172ZM7.1172 19.0585C6.79298 19.0585 6.5297 18.7952 6.5297 18.4702C6.5297 18.146 6.79298 17.8819 7.1172 17.8819H16.5296C16.8538 17.8819 17.1171 18.146 17.1171 18.4702C17.1171 18.7952 16.8538 19.0585 16.5296 19.0585H7.1172Z"
                fill="currentColor"
            />
            {mode === 'collapse' ? (
                <>
                    <path
                        d="M6.47654 6.12116L8.44086 4.15683C8.65013 3.94756 8.98943 3.94756 9.19838 4.15683C9.40765 4.3661 9.40765 4.70539 9.19838 4.91435L8.14871 5.96401L11.9942 5.96429C12.29 5.96429 12.5332 6.20426 12.5332 6.50002C12.5332 6.79578 12.29 7.03575 11.9942 7.03575H8.14871L9.19867 8.08541C9.40794 8.29468 9.40794 8.63397 9.19867 8.84293C8.9894 9.0522 8.6501 9.0522 8.44115 8.84293L6.47682 6.8786C6.26755 6.66961 6.26755 6.33039 6.47654 6.12116Z"
                        fill="currentColor"
                    />
                    <path
                        d="M17.0947 6.12116L15.1304 4.15683C14.9211 3.94756 14.5818 3.94756 14.3729 4.15683C14.1636 4.3661 14.1636 4.70539 14.3729 4.91435L15.4225 5.96401L11.6771 5.96429C11.3813 5.96429 11.0371 6.20426 11.0371 6.50002C11.0371 6.79578 11.3813 7.03575 11.6771 7.03575H15.4225L14.3726 8.08541C14.1633 8.29468 14.1633 8.63397 14.3726 8.84293C14.5818 9.0522 14.9211 9.0522 15.1301 8.84293L17.0944 6.8786C17.3037 6.66961 17.3037 6.33039 17.0947 6.12116Z"
                        fill="currentColor"
                    />
                </>
            ) : (
                <>
                    <path
                        d="M12.4765 6.12116L14.4408 4.15683C14.6501 3.94756 14.9894 3.94756 15.1984 4.15683C15.4076 4.3661 15.4076 4.70539 15.1984 4.91435L14.1487 5.96401L16.9942 5.96429C17.29 5.96429 17.5332 6.20426 17.5332 6.50002C17.5332 6.79578 17.29 7.03575 16.9942 7.03575H14.1487L15.1986 8.08541C15.4079 8.29468 15.4079 8.63397 15.1986 8.84293C14.9894 9.0522 14.6501 9.0522 14.4411 8.84293L12.4768 6.8786C12.2675 6.66961 12.2675 6.33039 12.4765 6.12116Z"
                        fill="currentColor"
                    />
                    <path
                        d="M11.3818 6.12116L9.4175 4.15683C9.20823 3.94756 8.86894 3.94756 8.65998 4.15683C8.45071 4.3661 8.45071 4.70539 8.65998 4.91435L9.70965 5.96401L6.96422 5.96429C6.66846 5.96429 6.32422 6.20426 6.32422 6.50002C6.32422 6.79578 6.66846 7.03575 6.96422 7.03575H9.70965L8.6597 8.08541C8.45043 8.29468 8.45043 8.63397 8.6597 8.84293C8.86896 9.0522 9.20826 9.0522 9.41721 8.84293L11.3815 6.8786C11.5908 6.66961 11.5908 6.33039 11.3818 6.12116Z"
                        fill="currentColor"
                    />
                </>
            )}
        </LemonIconBase>
    )
}

export function IconAdsClick(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase {...props}>
            <path
                d="M11.71,17.99C8.53,17.84,6,15.22,6,12c0-3.31,2.69-6,6-6c3.22,0,5.84,2.53,5.99,5.71l-2.1-0.63C15.48,9.31,13.89,8,12,8 c-2.21,0-4,1.79-4,4c0,1.89,1.31,3.48,3.08,3.89L11.71,17.99z M22,12c0,0.3-0.01,0.6-0.04,0.9l-1.97-0.59C20,12.21,20,12.1,20,12 c0-4.42-3.58-8-8-8s-8,3.58-8,8s3.58,8,8,8c0.1,0,0.21,0,0.31-0.01l0.59,1.97C12.6,21.99,12.3,22,12,22C6.48,22,2,17.52,2,12 C2,6.48,6.48,2,12,2S22,6.48,22,12z M18.23,16.26L22,15l-10-3l3,10l1.26-3.77l4.27,4.27l1.98-1.98L18.23,16.26z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconFingerprint(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="1 1 23 23" {...props}>
            <path
                d="M13.1427 20.9999C10.8077 19.5438 9.25254 16.9522 9.25254 13.9968C9.25254 12.4783 10.4833 11.2476 12.0008 11.2476C13.5184 11.2476 14.7491 12.4783 14.7491 13.9968C14.7491 15.5153 15.9798 16.746 17.4974 16.746C19.0149 16.746 20.2457 15.5153 20.2457 13.9968C20.2457 9.44139 16.5544 5.74922 12.0017 5.74922C7.44907 5.74922 3.75781 9.44139 3.75781 13.9968C3.75781 15.0122 3.87145 16.001 4.08038 16.954M8.49027 20.2989C7.23938 18.5138 6.50351 16.3419 6.50351 13.9968C6.50351 10.9599 8.96405 8.49844 11.9992 8.49844C15.0343 8.49844 17.4948 10.9599 17.4948 13.9968M17.7927 19.4806C17.6937 19.4861 17.5966 19.4953 17.4967 19.4953C14.4616 19.4953 12.0011 17.0338 12.0011 13.9969M19.6734 6.47682C17.7993 4.34802 15.0593 3 12.0004 3C8.94141 3 6.20138 4.34802 4.32734 6.47682"
                stroke="currentColor"
                strokeWidth="1"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </LemonIconBase>
    )
}

export function IconVerticalAlignCenter(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 24 24" {...props}>
            <path
                d="M11.8214 24V17.0667L8.97143 19.8667L8.01091 18.923L12.5 14.5127L16.9891 18.923L16.0286 19.8667L13.1786 17.0667V24H11.8214ZM3 12.6667V11.3333H22V12.6667H3ZM12.5 9.48733L8.01091 5.077L8.97143 4.13333L11.8214 6.93333V0H13.1786V6.93333L16.0286 4.13333L16.9891 5.077L12.5 9.48733Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

/** @deprecated and will be replaced soon*/
export function IconRecordingClip(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 24 24" {...props}>
            {/* Film frame, scaled down and shifted right */}
            <g transform="translate(9 6) scale(0.66)">
                <path d="M0 0h24v24H0z" fill="none" />
                <path
                    d="M4 6a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2z"
                    stroke="currentColor"
                    strokeWidth="1"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                />
                <path d="M8 4v16" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
                <path d="M16 4v16" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
                <path d="M4 8h4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
                <path d="M4 12h16" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
                <path d="M4 16h4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
                <path d="M16 8h4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
                <path d="M16 16h4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
            </g>

            {/* Scissors, shifted left */}
            <g transform="translate(-2 0)">
                <path d="M0 0h24v24H0z" fill="none" />
                <path
                    d="M6 7a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"
                    stroke="currentColor"
                    strokeWidth="1.3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                />
                <path
                    d="M6 17a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"
                    stroke="currentColor"
                    strokeWidth="1.3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                />
                <path
                    d="M8.6 8.6l10.4 10.4"
                    stroke="currentColor"
                    strokeWidth="1.3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                />
                <path
                    d="M8.6 15.4l10.4 -10.4"
                    stroke="currentColor"
                    strokeWidth="1.3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                />
            </g>
        </LemonIconBase>
    )
}

export function IconGhost(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 24 24" {...props}>
            <path
                d="M12 2C15.5 2 18 5 19 8C22 9 23 11.73 23 14L20.2253 14.7928C19.796 14.9154 19.5 15.3078 19.5 15.7543V17.25C19.5 18.2165 18.7165 19 17.75 19H17.1536C16.4825 19 15.8562 19.3366 15.4858 19.8962C14.5576 21.2987 13.3957 22 12 22C10.6043 22 9.44238 21.2987 8.5142 19.8962C8.14383 19.3366 7.51746 19 6.84636 19H6.25C5.2835 19 4.5 18.2165 4.5 17.25V15.7543C4.5 15.3078 4.20402 14.9154 3.77472 14.7928L1 14C1 11.7337 2 9 5 8C6 5 8.5 2 12 2ZM12 4C9.8906 4 7.93534 5.78788 6.98864 8.37148L6.89737 8.63246L6.58114 9.58114L5.63246 9.89737C4.37721 10.3158 3.56485 11.238 3.20834 12.4564L3.185 12.543L4.32416 12.8697C5.55353 13.221 6.41845 14.3095 6.49454 15.5727L6.5 15.7543V17H6.84636C8.1096 17 9.29359 17.5963 10.0461 18.5996L10.182 18.7925C10.7584 19.6634 11.3162 20 12 20C12.6382 20 13.1667 19.7068 13.7029 18.9596L13.818 18.7925C14.5151 17.739 15.6658 17.0807 16.9178 17.0069L17.1536 17H17.5V15.7543C17.5 14.4757 18.309 13.3451 19.5027 12.9249L19.6758 12.8697L20.815 12.543L20.7918 12.4555C20.4554 11.3047 19.7124 10.4193 18.5728 9.97176L18.3675 9.89737L17.4189 9.58114L17.1026 8.63246C16.1948 5.90906 14.1797 4 12 4ZM12 12C12.8284 12 13.5 13.1193 13.5 14.5C13.5 15.8807 12.8284 17 12 17C11.1716 17 10.5 15.8807 10.5 14.5C10.5 13.1193 11.1716 12 12 12ZM9.5 8C10.3284 8 11 8.67157 11 9.5C11 10.3284 10.3284 11 9.5 11C8.67157 11 8 10.3284 8 9.5C8 8.67157 8.67157 8 9.5 8ZM14.5 8C15.3284 8 16 8.67157 16 9.5C16 10.3284 15.3284 11 14.5 11C13.6716 11 13 10.3284 13 9.5C13 8.67157 13.6716 8 14.5 8Z"
                fill="currentColor"
            />
        </LemonIconBase>
    )
}

export function IconSanta(props: LemonIconProps): JSX.Element {
    return (
        <LemonIconBase viewBox="0 0 24 24" {...props}>
            <path
                d="M7.6302 10C6.65914 10.8046 5.10543 13.7999 6.65914 15.3447C7.81902 16.4979 9.59225 15.9293 10.888 15.1652C11.3833 14.8732 11.6309 14.7272 11.7885 14.6931C11.9737 14.653 12.0263 14.653 12.2115 14.6931C12.3691 14.7272 12.6167 14.8732 13.112 15.1652C14.4077 15.9293 16.181 16.4979 17.3409 15.3447C18.8946 13.7999 17.3409 10.8046 16.3698 10M7.4985 10C4.17378 11.6 0.265086 16.24 11.9994 22M16.5013 10C19.8261 11.6 23.7351 16.24 12.0008 22M7 7.00003C7 5.00008 11 -2 19 4.00001C14.9999 2.50002 14.9985 5.00005 16.9995 7.00005M10 12.5H10.01M14 12.5H14.01M11 18C11.103 18.0515 11.1545 18.0773 11.2048 18.099C11.7121 18.3189 12.2879 18.3189 12.7952 18.099C12.8455 18.0773 12.897 18.0515 13 18M6.5 10H17.5C18.3284 10 19 9.32843 19 8.5C19 7.67157 18.3284 7 17.5 7H6.5C5.67157 7 5 7.67157 5 8.5C5 9.32843 5.67157 10 6.5 10ZM20 4C20 4.55228 19.5523 5 19 5C18.4477 5 18 4.55228 18 4C18 3.44772 18.4477 3 19 3C19.5523 3 20 3.44772 20 4Z"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke="currentColor"
                fill="none"
            />
        </LemonIconBase>
    )
}
