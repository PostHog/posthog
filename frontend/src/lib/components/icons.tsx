// Loads custom icons (some icons may come from a third-party library)
import clsx from 'clsx'
import React, { CSSProperties, PropsWithChildren, SVGAttributes } from 'react'
import './icons.scss'
import { LemonBubble } from './LemonBubble/LemonBubble'

interface IconWithCountProps {
    count: number
    showZero?: boolean
}

export function IconWithCount({ count, children, showZero }: PropsWithChildren<IconWithCountProps>): JSX.Element {
    return (
        <span style={{ position: 'relative', display: 'inline-flex' }}>
            {children}
            <LemonBubble count={count} size="small" position="top-right" showZero={showZero} />
        </span>
    )
}

interface SvgIconProps {
    color?: string
    fontSize?: string
    style?: CSSProperties
    className?: string
}

const SvgIcon: React.FC<SVGAttributes<SVGSVGElement>> = ({ className, ...props }) => (
    <svg
        className={clsx('LemonIcon', className)}
        width="1em"
        height="1em"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        {...props}
    />
)

export function IconJavascript(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 32 32" {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M0 0H32V32H0V0ZM23.8479 14.5396C22.6981 14.6309 21.7338 15.0446 21.0159 15.7564C20.2768 16.4894 19.9239 17.3837 19.9239 18.5183C19.9239 20.2157 20.6205 21.402 22.1749 22.3419C22.5703 22.5792 23.1087 22.8377 24.0395 23.2392C25.308 23.7837 25.7794 24.0423 26.0806 24.3647C26.4517 24.7632 26.5551 25.3989 26.3209 25.8856C26.2752 25.9799 26.1566 26.1381 26.0502 26.2446C25.6912 26.6065 25.1254 26.7982 24.4228 26.7982C23.2365 26.7982 22.3513 26.3115 21.6395 25.259C21.5422 25.1191 21.454 25.0035 21.4418 25.0035C21.4144 25.0035 19.0996 26.3389 19.0509 26.3845C19.0205 26.4119 19.0449 26.4757 19.1635 26.6704C20.0882 28.2278 21.5331 29.1404 23.4859 29.402C23.9969 29.4719 24.9551 29.4689 25.4448 29.402C26.6737 29.2286 27.5954 28.821 28.3102 28.1275C29.0707 27.3944 29.4448 26.4453 29.4448 25.256C29.4448 24.4955 29.3201 23.9024 29.0372 23.3153C28.8425 22.9138 28.6479 22.643 28.3133 22.3024C27.6714 21.6514 26.841 21.1586 25.1832 20.4468C23.93 19.9084 23.5102 19.6773 23.2334 19.3822C22.9688 19.0993 22.8562 18.7678 22.8806 18.3541C22.9019 18.0256 22.9931 17.8035 23.1939 17.5875C23.4829 17.2742 23.8175 17.1434 24.3346 17.1465C24.9216 17.1465 25.3019 17.2986 25.6882 17.6879C25.8251 17.8217 26.0015 18.0377 26.0836 18.1685C26.1779 18.3176 26.2479 18.3997 26.2722 18.3906C26.3513 18.3571 28.5627 16.9275 28.5627 16.9062C28.5627 16.894 28.4501 16.7176 28.3133 16.5107C28.0212 16.0727 27.495 15.5252 27.133 15.2849C26.4638 14.8408 25.749 14.6126 24.8061 14.5427C24.3437 14.5062 24.2829 14.5062 23.8479 14.5396ZM14.3695 25.4449L14.3787 20.0669L14.3908 14.692H15.8783H17.3688V20.0852C17.3688 23.6623 17.3566 25.5635 17.3384 25.7338C17.1285 27.416 16.3346 28.5475 14.981 29.095C13.8524 29.5483 12.3133 29.5848 11.1148 29.1863C9.9802 28.8091 9.03723 27.9878 8.49274 26.9019L8.40149 26.7194L9.60301 25.9893C10.2631 25.5909 10.8137 25.2593 10.8258 25.2532C10.8349 25.2502 10.914 25.3688 11.0022 25.5148C11.5467 26.4456 12.0152 26.7772 12.7969 26.7741C13.3445 26.7711 13.673 26.6646 13.9285 26.4091C14.111 26.2266 14.2144 26.0289 14.3026 25.6973L14.3695 25.4449Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconPython(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 32 32" {...props}>
            <path
                d="M15.8846 0C7.76106 5.79599e-07 8.26835 3.52288 8.26835 3.52288L8.2774 7.17254H16.0295V8.26835H5.19828C5.19828 8.26835 0 7.67882 0 15.8756C-5.79599e-07 24.0724 4.53718 23.7817 4.53718 23.7817H7.24499V19.9781C7.24499 19.9781 7.09903 15.4409 11.7097 15.4409C16.3204 15.4409 19.3985 15.4409 19.3985 15.4409C19.3985 15.4409 23.7183 15.5107 23.7183 11.266C23.7183 7.02121 23.7183 4.24738 23.7183 4.24738C23.7183 4.24738 24.3742 0 15.8846 0ZM11.6101 2.45424C12.3814 2.45424 13.0048 3.07762 13.0048 3.8489C13.0048 4.62018 12.3814 5.24356 11.6101 5.24356C10.8388 5.24356 10.2154 4.62018 10.2154 3.8489C10.2154 3.07762 10.8388 2.45424 11.6101 2.45424Z"
                fill="currentColor"
            />
            <path
                d="M16.1154 31.8333C24.2389 31.8333 23.7317 28.3104 23.7317 28.3104L23.7226 24.6607H15.9705V23.5649H26.8017C26.8017 23.5649 32 24.1544 32 15.9577C32 7.76089 27.4628 8.05157 27.4628 8.05157H24.755V11.8552C24.755 11.8552 24.901 16.3924 20.2903 16.3924C15.6796 16.3924 12.6015 16.3924 12.6015 16.3924C12.6015 16.3924 8.28171 16.3225 8.28171 20.5673C8.28171 24.812 8.28171 27.5859 8.28171 27.5859C8.28171 27.5859 7.62584 31.8333 16.1154 31.8333ZM20.3899 29.379C19.6186 29.379 18.9952 28.7556 18.9952 27.9844C18.9952 27.2131 19.6186 26.5897 20.3899 26.5897C21.1612 26.5897 21.7846 27.2131 21.7846 27.9844C21.7846 28.7556 21.1612 29.379 20.3899 29.379Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconHandClick(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 18 18" {...props}>
            <path
                d="M14.9942 7.90164C14.9942 7.82992 14.9583 7.46993 14.6342 7.10993C14.2925 6.71407 13.7524 6.49822 13.05 6.44407C12.9783 6.33579 12.8883 6.22822 12.7442 6.11993C12.3483 5.81407 11.7359 5.65164 10.9442 5.63407C10.8724 5.54407 10.7459 5.43578 10.6024 5.32822C10.2425 5.0765 9.79245 4.93236 9.23416 4.87822V3.41993C9.23416 3.27579 9.25244 2.66407 8.83831 2.23164C8.65831 2.03335 8.31659 1.79993 7.74002 1.79993C7.14587 1.79993 6.80416 2.03407 6.60587 2.23164C6.22759 2.64578 6.22759 3.18578 6.22759 3.31164V8.46C5.88587 8.1 5.50759 7.70414 5.29173 7.56C4.84173 7.21829 3.99587 7.39828 3.51002 7.75829C3.04173 8.1 2.88002 8.62243 3.06002 9.12658C3.38416 10.0266 4.19416 10.9266 4.39173 11.1424C4.57173 11.4841 5.38173 12.9782 6.10173 13.5182C6.48002 13.8065 6.76759 14.9941 6.84002 15.7499L6.87588 16.1457H13.6801V14.364C13.7701 14.1123 13.9859 13.5723 14.2201 13.3199C14.7783 12.7616 14.9583 11.3582 14.9583 10.9257V7.91986L14.9942 7.90164ZM14.1117 10.89C14.1117 11.4117 13.8959 12.4017 13.6259 12.6717C13.1576 13.14 12.87 14.04 12.8517 14.13L12.8335 14.1841V15.2283H7.68583C7.64997 15.03 7.61411 14.7783 7.54169 14.5083C7.32583 13.6441 7.03754 13.0866 6.65998 12.7983C6.13826 12.4024 5.39998 11.1241 5.16583 10.6566L5.09411 10.5484C5.09411 10.5301 4.2124 9.63008 3.90582 8.80251C3.86996 8.69423 3.86996 8.60422 3.99582 8.47836C4.22997 8.26251 4.67997 8.20836 4.78754 8.24422C5.05754 8.46008 5.88582 9.34251 6.35339 9.86422L7.12754 10.7284L7.12824 3.29418V3.25762C7.12824 3.1859 7.14652 2.95176 7.27238 2.82591C7.36238 2.71763 7.52409 2.66419 7.75824 2.66419C7.95652 2.66419 8.09995 2.71833 8.20824 2.80833C8.35238 2.97005 8.36996 3.25833 8.36996 3.36662V8.02826H9.25167V5.7599C10.0617 5.8499 10.2958 6.19161 10.3317 6.24575L10.3675 6.33575V8.02747H11.2492V6.53332C12.0051 6.60504 12.2934 6.83918 12.3651 6.94747V8.65747H13.2468V7.34332C14.021 7.4516 14.1468 7.86504 14.1651 7.95504L14.1658 10.8899L14.1117 10.89Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function SortableDragIcon(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 16 16" {...props}>
            <path
                d="M2 6C2 6.13132 2.02587 6.26136 2.07612 6.38268C2.12638 6.50401 2.20003 6.61425 2.29289 6.70711C2.38575 6.79997 2.49599 6.87362 2.61732 6.92388C2.73864 6.97413 2.86868 7 3 7C3.13132 7 3.26136 6.97413 3.38268 6.92388C3.50401 6.87362 3.61425 6.79997 3.70711 6.70711C3.79997 6.61425 3.87362 6.50401 3.92388 6.38268C3.97413 6.26136 4 6.13132 4 6C4 5.86868 3.97413 5.73864 3.92388 5.61732C3.87362 5.49599 3.79997 5.38575 3.70711 5.29289C3.61425 5.20003 3.50401 5.12638 3.38268 5.07612C3.26136 5.02587 3.13132 5 3 5C2.86868 5 2.73864 5.02587 2.61732 5.07612C2.49599 5.12638 2.38575 5.20003 2.29289 5.29289C2.20003 5.38575 2.12638 5.49599 2.07612 5.61732C2.02587 5.73864 2 5.86868 2 6ZM7 6C7 6.26522 7.10536 6.51957 7.29289 6.70711C7.48043 6.89464 7.73478 7 8 7C8.26522 7 8.51957 6.89464 8.70711 6.70711C8.89464 6.51957 9 6.26522 9 6C9 5.73478 8.89464 5.48043 8.70711 5.29289C8.51957 5.10536 8.26522 5 8 5C7.73478 5 7.48043 5.10536 7.29289 5.29289C7.10536 5.48043 7 5.73478 7 6ZM12 6C12 6.26522 12.1054 6.51957 12.2929 6.70711C12.4804 6.89464 12.7348 7 13 7C13.2652 7 13.5196 6.89464 13.7071 6.70711C13.8946 6.51957 14 6.26522 14 6C14 5.73478 13.8946 5.48043 13.7071 5.29289C13.5196 5.10536 13.2652 5 13 5C12.7348 5 12.4804 5.10536 12.2929 5.29289C12.1054 5.48043 12 5.73478 12 6Z"
                fill="currentColor"
            />
            <path
                d="M2 10C2 10.1313 2.02587 10.2614 2.07612 10.3827C2.12638 10.504 2.20003 10.6142 2.29289 10.7071C2.38575 10.8 2.49599 10.8736 2.61732 10.9239C2.73864 10.9741 2.86868 11 3 11C3.13132 11 3.26136 10.9741 3.38268 10.9239C3.50401 10.8736 3.61425 10.8 3.70711 10.7071C3.79997 10.6142 3.87362 10.504 3.92388 10.3827C3.97413 10.2614 4 10.1313 4 10C4 9.86868 3.97413 9.73864 3.92388 9.61732C3.87362 9.49599 3.79997 9.38575 3.70711 9.29289C3.61425 9.20003 3.50401 9.12638 3.38268 9.07612C3.26136 9.02587 3.13132 9 3 9C2.86868 9 2.73864 9.02587 2.61732 9.07612C2.49599 9.12638 2.38575 9.20003 2.29289 9.29289C2.20003 9.38575 2.12638 9.49599 2.07612 9.61732C2.02587 9.73864 2 9.86868 2 10ZM7 10C7 10.2652 7.10536 10.5196 7.29289 10.7071C7.48043 10.8946 7.73478 11 8 11C8.26522 11 8.51957 10.8946 8.70711 10.7071C8.89464 10.5196 9 10.2652 9 10C9 9.73478 8.89464 9.48043 8.70711 9.29289C8.51957 9.10536 8.26522 9 8 9C7.73478 9 7.48043 9.10536 7.29289 9.29289C7.10536 9.48043 7 9.73478 7 10ZM12 10C12 10.2652 12.1054 10.5196 12.2929 10.7071C12.4804 10.8946 12.7348 11 13 11C13.2652 11 13.5196 10.8946 13.7071 10.7071C13.8946 10.5196 14 10.2652 14 10C14 9.73478 13.8946 9.48043 13.7071 9.29289C13.5196 9.10536 13.2652 9 13 9C12.7348 9 12.4804 9.10536 12.2929 9.29289C12.1054 9.48043 12 9.73478 12 10Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function DiveIcon(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 17 18" {...props}>
            <path
                d="M16.5 18C16.1484 18 15.829 17.9195 15.5306 17.7832C15.2223 17.6385 14.8759 17 14.5145 17C14.1505 17 13.806 17.6385 13.4956 17.7832C13.195 17.9195 12.8443 18 12.4928 18C12.1415 18 11.8218 17.9195 11.5236 17.7832C11.2108 17.6385 10.8696 17 10.506 17C10.142 17 9.79468 17.6385 9.48834 17.7832C9.18778 17.9195 8.83707 18 8.48551 18C8.13446 18 7.81451 17.9195 7.51225 17.7832C7.20574 17.6385 6.85955 17 6.5 17C6.1362 17 5.78743 17.6385 5.48092 17.7832C5.1807 17.9195 4.82983 18 4.48048 18C4.12909 18 3.80948 17.9195 3.50688 17.7832C3.20037 17.6385 2.85418 17 2.4948 17C2.131 17 1.78223 17.6385 1.47606 17.7832C1.1755 17.9195 0.820894 18 0.468994 18V16.5042C0.820894 16.5042 1.1755 16.4237 1.47606 16.2855C1.78223 16.145 2.131 15.5063 2.4948 15.5063C2.85435 15.5063 3.20054 16.145 3.50688 16.2855C3.80948 16.4237 4.12909 16.5042 4.48048 16.5042C4.82983 16.5042 5.1807 16.4237 5.48075 16.2855C5.78726 16.145 6.13603 15.5064 6.49983 15.5064C6.85938 15.5064 7.20557 16.145 7.51208 16.2855C7.81434 16.4237 8.13429 16.5042 8.48534 16.5042C8.8369 16.5042 9.18761 16.4237 9.48817 16.2855C9.79468 16.145 10.142 15.5064 10.5058 15.5064C10.8696 15.5064 11.2106 16.145 11.5234 16.2855C11.8216 16.4237 12.1414 16.5042 12.4926 16.5042C12.8441 16.5042 13.1948 16.4237 13.4954 16.2855C13.8058 16.145 14.1505 15.5064 14.5143 15.5064C14.8757 15.5064 15.2221 16.145 15.5305 16.2855C15.8288 16.4237 16.1483 16.5042 16.4998 16.5042L16.5 18Z"
                fill="currentColor"
            />
            <path
                d="M4.35065 9.73315C5.09678 9.73315 5.70368 9.11962 5.70368 8.36346C5.70368 7.60951 5.09678 7.00006 4.35065 7.00006C3.6069 7.00006 3 7.60934 3 8.36346C3 9.11962 3.60707 9.73315 4.35065 9.73315Z"
                fill="currentColor"
            />
            <path
                d="M5.21321 14.3911C5.00071 14.7566 4.53508 14.8826 4.17315 14.6634C3.80935 14.4509 3.68661 13.9778 3.89724 13.6123L7.03374 8.15225C7.14815 7.9457 7.3156 7.77621 7.51603 7.66469L11.5481 5.19391L14.2841 0.481854C14.5437 0.0230238 15.1235 -0.135926 15.5776 0.126554C16.029 0.393114 16.1845 0.977574 15.9251 1.43402L12.6453 7.07989C12.5331 7.28457 12.3655 7.45423 12.1608 7.56745L7.40383 10.5566L5.21321 14.3911Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconInfinity(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 14 6" fill="none" {...props}>
            <path
                d="M10.6817 0C9.87877 0 9.12041 0.312268 8.57952 0.85316L4.65944 4.33271C4.30256 4.68959 3.82859 4.88476 3.32115 4.88476C2.2784 4.88476 1.43082 4.04275 1.43082 3C1.43082 1.95725 2.2784 1.11524 3.32115 1.11524C3.82859 1.11524 4.30256 1.31041 4.68175 1.68959L5.31186 2.24721L6.15386 1.5L5.45126 0.881041C4.88249 0.312268 4.12412 0 3.32115 0C1.65944 0 0.309998 1.34944 0.309998 3C0.309998 4.65056 1.65944 6 3.32115 6C4.12412 6 4.88249 5.68773 5.42338 5.14684L9.34346 1.66729C9.70033 1.31041 10.1743 1.11524 10.6817 1.11524C11.7245 1.11524 12.5721 1.95725 12.5721 3C12.5721 4.04275 11.7245 4.88476 10.6817 4.88476C10.1799 4.88476 9.70033 4.68959 9.32115 4.31041L8.68546 3.74721L7.84346 4.49442L8.55163 5.11896C9.12041 5.68216 9.8732 5.99442 10.6817 5.99442C12.3435 5.99442 13.6929 4.65056 13.6929 2.99442C13.6929 1.33829 12.3435 0 10.6817 0Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconTrendUp(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 81 60" fill="none" {...props}>
            <path
                d="M78.4688 50H10.125V2.5C10.125 1.11875 8.99227 0 7.59375 0H2.53125C1.13273 0 0 1.11875 0 2.5V55C0 57.7609 2.26705 60 5.0625 60H78.4688C79.8673 60 81 58.8812 81 57.5V52.5C81 51.1188 79.8673 50 78.4688 50ZM73.4062 5H54.7288C51.3464 5 49.6521 9.03906 52.0441 11.4016L57.1699 16.4641L45.5625 27.9297L33.9551 16.4656C31.9776 14.5125 28.7724 14.5125 26.7964 16.4656L15.9295 27.1984C14.9407 28.175 14.9407 29.7578 15.9295 30.7344L19.508 34.2688C20.4968 35.2453 22.0994 35.2453 23.0882 34.2688L30.375 27.0703L41.9824 38.5344C43.9599 40.4875 47.1651 40.4875 49.1411 38.5344L64.3286 23.5344L69.4543 28.5969C71.8464 30.9594 75.9359 29.2859 75.9359 25.9453V7.5C75.9375 6.11875 74.8048 5 73.4062 5Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Announcement icon. */
export function IconFeedbackWarning(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 32 32" {...props}>
            <path
                d="M26.6667 2.66663H5.33341C3.86675 2.66663 2.68008 3.86663 2.68008 5.33329L2.66675 29.3333L8.00008 24H26.6667C28.1334 24 29.3334 22.8 29.3334 21.3333V5.33329C29.3334 3.86663 28.1334 2.66663 26.6667 2.66663ZM26.6667 21.3333H6.89341L6.10675 22.12L5.33341 22.8933V5.33329H26.6667V21.3333ZM14.6667 16H17.3334V18.6666H14.6667V16ZM14.6667 7.99996H17.3334V13.3333H14.6667V7.99996Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconSelectEvents(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
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
        </SvgIcon>
    )
}

/** Material Design Logout icon. */
export function IconLogout(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m17 8-1.41 1.41 1.58 1.59h-8.17v2h8.17l-1.58 1.58 1.41 1.42 4-4zm-12-3h7v-2h-7c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h7v-2h-7z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design open in app icon.*/
export function IconOpenInApp(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon aria-hidden="true" role="img" preserveAspectRatio="xMidYMid meet" viewBox="0 0 24 24" {...props}>
            <path
                fill="currentColor"
                d="m12 10l-4 4h3v6h2v-6h3m3-10H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4v-2H5V8h14v10h-4v2h4a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2Z"
            />
        </SvgIcon>
    )
}

export function IconSelectProperties(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M3.73368 17.7247H2.26243C2.10826 17.7247 1.98761 17.5981 2.00102 17.4449C2.0458 16.5963 2.29659 15.7711 2.73195 15.0397C3.16732 14.3084 3.77433 13.6926 4.50115 13.245C3.89455 12.5788 3.5259 11.6995 3.5259 10.7303C3.5259 8.66865 5.19823 7 7.25933 7C9.32043 7 10.9928 8.66865 10.9928 10.7303C10.995 11.6602 10.6471 12.5572 10.0175 13.245C11.4452 14.1243 12.4238 15.6697 12.5176 17.4449C12.5195 17.481 12.5139 17.5171 12.5012 17.551C12.4886 17.5849 12.4691 17.6158 12.444 17.642C12.4189 17.6682 12.3888 17.689 12.3553 17.7032C12.3219 17.7174 12.2859 17.7247 12.2495 17.7247H10.7783C10.6375 17.7247 10.5236 17.6148 10.5135 17.4749C10.3862 15.7929 8.97189 14.4607 7.25598 14.4607C5.54007 14.4607 4.12579 15.7929 3.99844 17.4749C3.98839 17.6148 3.87444 17.7247 3.73368 17.7247ZM8.9884 10.73C8.9884 9.77414 8.21088 8.9981 7.25574 8.9981C6.3006 8.9981 5.52308 9.77414 5.52308 10.73C5.52308 11.6859 6.3006 12.462 7.25574 12.462C8.21088 12.462 8.9884 11.6859 8.9884 10.73ZM14.8829 9.9675H21.7379C21.8819 9.9675 22 10.0436 22 10.1365V11.1508C22 11.2437 21.8819 11.3198 21.7379 11.3198H14.8829C14.7389 11.3198 14.6208 11.2437 14.6208 11.1508V10.1365C14.6208 10.0436 14.7389 9.9675 14.8829 9.9675ZM14.7057 13.0102H19.261C19.309 13.0102 19.3459 13.0863 19.3459 13.1792V14.1935C19.3459 14.2864 19.309 14.3625 19.261 14.3625H14.7057C14.6577 14.3625 14.6208 14.2864 14.6208 14.1935V13.1792C14.6208 13.0863 14.6577 13.0102 14.7057 13.0102Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Unfold More icon. */
export function IconUnfoldMore(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                d="M12.0002 5.83L15.1702 9L16.5802 7.59L12.0002 3L7.41016 7.59L8.83016 9L12.0002 5.83ZM12.0002 18.17L8.83016 15L7.42016 16.41L12.0002 21L16.5902 16.41L15.1702 15L12.0002 18.17Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Unfold Less icon. */
export function IconUnfoldLess(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                d="M7.41016 18.59L8.83016 20L12.0002 16.83L15.1702 20L16.5802 18.59L12.0002 14L7.41016 18.59ZM16.5902 5.41L15.1702 4L12.0002 7.17L8.83016 4L7.41016 5.41L12.0002 10L16.5902 5.41Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Swap Horiz Less icon. */
export function IconSwapHoriz(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path d="m6.99 11-3.99 4 3.99 4v-3h7.01v-2h-7.01zm14.01-2-3.99-4v3h-7.01v2h7.01v3z" fill="currentColor" />
        </SvgIcon>
    )
}

/** Material Design Chevron Left icon. */
export function IconChevronLeft(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="M13.9999 6L15.4099 7.41L10.8299 12L15.4099 16.59L13.9999 18L7.99991 12L13.9999 6Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Chevron Right icon. */
export function IconChevronRight(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="M10.0001 6L8.59009 7.41L13.1701 12L8.59009 16.59L10.0001 18L16.0001 12L10.0001 6Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Add icon. */
export function IconPlus(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path d="m19 13h-6v6h-2v-6h-6v-2h6v-6h2v6h6z" fill="currentColor" />
        </SvgIcon>
    )
}

/** A plus button like IconPlus, but more compact */
export function IconPlusMini(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" height="24" viewBox="0 0 24 24" width="24" {...props}>
            <path
                d="m16.7917 11.1667h-3.9584v-3.95837c0-.11458-.0937-.20833-.2083-.20833h-1.25c-.1146 0-.2083.09375-.2083.20833v3.95837h-3.95837c-.11458 0-.20833.0937-.20833.2083v1.25c0 .1146.09375.2083.20833.2083h3.95837v3.9584c0 .1145.0937.2083.2083.2083h1.25c.1146 0 .2083-.0938.2083-.2083v-3.9584h3.9584c.1145 0 .2083-.0937.2083-.2083v-1.25c0-.1146-.0938-.2083-.2083-.2083z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Task Alt icon. */
export function IconCheckmark(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" viewBox="0 0 24 24" {...props}>
            <path
                d="m21 5.862-10.269 10.278-3.816-3.816 1.269-1.269 2.547 2.547 9-9zm-1.989 4.536c.117.513.189 1.053.189 1.602 0 3.978-3.222 7.2-7.2 7.2s-7.2-3.222-7.2-7.2 3.222-7.2 7.2-7.2c1.422 0 2.736.414 3.852 1.125l1.296-1.296c-1.458-1.026-3.231-1.629-5.148-1.629-4.968 0-9 4.032-9 9s4.032 9 9 9 9-4.032 9-9c0-1.071-.198-2.097-.54-3.051z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Radio Button Unchecked icon. */
export function IconRadioButtonUnchecked(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon height="24px" viewBox="0 0 24 24" width="24px" fill="currentColor" {...props}>
            <path d="M0 0h24v24H0z" fill="none" />
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z" />
        </SvgIcon>
    )
}

/** Material Design Downloading icon. */
export function IconUpdate(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m18.32 4.2601c-1.48-1.21-3.31-2.01-5.32-2.21v2.02c1.46.18 2.79.76 3.9 1.62zm1.61 6.74h2.02c-.2-2.01-1-3.84-2.21-5.32l-1.43 1.42c.86 1.11 1.44 2.44 1.62 3.9zm-1.62 5.9 1.43 1.43c1.21-1.48 2.01-3.32 2.21-5.32h-2.02c-.18 1.45-.76 2.78-1.62 3.89zm-5.31 3.03v2.02c2.01-.2 3.84-1 5.32-2.21l-1.43-1.43c-1.1.86-2.43 1.44-3.89 1.62zm2.59-9.34-2.59 2.58v-6.17h-2v6.17l-2.59-2.59-1.41 1.42 5 5 5-5zm-4.59 9.34v2.02c-5.05-.5-9-4.76-9-9.95s3.95-9.45 9-9.95v2.02c-3.95.49-7 3.85-7 7.93s3.05 7.44 7 7.93z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Offline Bolt icon. */
export function IconOffline(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" viewBox="0 0 24 24" {...props}>
            <path
                d="m12 2.02c-5.51 0-9.98 4.47-9.98 9.98s4.47 9.98 9.98 9.98 9.98-4.47 9.98-9.98-4.47-9.98-9.98-9.98zm0 17.96c-4.4 0-7.98-3.58-7.98-7.98s3.58-7.98 7.98-7.98 7.98 3.58 7.98 7.98-3.58 7.98-7.98 7.98zm.75-14.98-4.5 8.5h3.14v5.5l4.36-8.5h-3z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Settings icon. */
export function IconSettings(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m19.43 12.98c.04-.32.07-.64.07-.98s-.03-.66-.07-.98l2.11-1.65c.19-.15.24-.42.12-.64l-2-3.46c-.09-.16-.26-.25-.44-.25-.06 0-.12.01-.17.03l-2.49 1c-.52-.4-1.08-.73-1.69-.98l-.38-2.65c-.03-.24-.24-.42-.49-.42h-4.00004c-.25 0-.46.18-.49.42l-.38 2.65c-.61.25-1.17.59-1.69.98l-2.49-1c-.06-.02-.12-.03-.18-.03-.17 0-.34.09-.43.25l-2 3.46c-.13.22-.07.49.12.64l2.11 1.65c-.04.32-.07.65-.07.98s.03.66.07.98l-2.11 1.65c-.19.15-.24.42-.12.64l2 3.46c.09.16.26.25.44.25.06 0 .12-.01.17-.03l2.49-1c.52.4 1.08.73 1.69.98l.38 2.65c.03.24.24.42.49.42h4.00004c.25 0 .46-.18.49-.42l.38-2.65c.61-.25 1.17-.59 1.69-.98l2.49 1c.06.02.12.03.18.03.17 0 .34-.09.43-.25l2-3.46c.12-.22.07-.49-.12-.64zm-1.98-1.71c.04.31.05.52.05.73s-.02.43-.05.73l-.14 1.13.89.7 1.08.84-.7 1.21-1.27-.51-1.04-.42-.9.68c-.43.32-.84.56-1.25.73l-1.06.43-.16 1.13-.2 1.35h-1.4l-.19-1.35-.16-1.13-1.06004-.43c-.43-.18-.83-.41-1.23-.71l-.91-.7-1.06.43-1.27.51-.7-1.21 1.08-.84.89-.7-.14-1.13c-.03-.31-.05-.54-.05-.74s.02-.43.05-.73l.14-1.13-.89-.7-1.08-.84.7-1.21 1.27.51 1.04.42.9-.68c.43-.32.84-.56 1.25-.73l1.06004-.43.16-1.13.2-1.35h1.39l.19 1.35.16 1.13 1.06.43c.43.18.83.41 1.23.71l.91.7 1.06-.43 1.27-.51.7 1.21-1.07.85-.89.7zm-5.45-3.27c-2.21004 0-4.00004 1.79-4.00004 4s1.79 4 4.00004 4c2.21 0 4-1.79 4-4s-1.79-4-4-4zm0 6c-1.1 0-2.00004-.9-2.00004-2s.90004-2 2.00004-2 2 .9 2 2-.9 2-2 2z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Dns icon. */
export function IconServer(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" viewBox="0 0 24 24" {...props}>
            <path d="m0 0h24v24h-24z" fill="none" />
            <path
                d="m19 15v4h-14v-4zm1-2h-16c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1zm-13 5.5c-.82 0-1.5-.67-1.5-1.5s.68-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm12-13.5v4h-14v-4zm1-2h-16c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1zm-13 5.5c-.82 0-1.5-.67-1.5-1.5s.68-1.5 1.5-1.5 1.5.68 1.5 1.5-.67 1.5-1.5 1.5z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Menu icon. */
export function IconMenu(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path d="m3 18h18v-2h-18zm0-5h18v-2h-18zm0-7v2h18v-2z" fill="currentColor" />
        </SvgIcon>
    )
}

/** Material Design Menu Open icon. */
export function IconMenuOpen(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m3 18h13v-2h-13zm0-5h10v-2h-10zm0-7v2h13v-2zm18 9.59-3.58-3.59 3.58-3.59-1.41-1.41-5 5 5 5z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Sync icon. */
export function IconSync(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m12.5 4v-3l-4 4 4 4v-3c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46c.78-1.23 1.24-2.69 1.24-4.26 0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8l-1.46-1.46c-.78 1.23-1.24 2.69-1.24 4.26 0 4.42 3.58 8 8 8v3l4-4-4-4z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Subtitles icon. */
export function IconSubtitles(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m20 4h-16c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2v-12c0-1.1-.9-2-2-2zm0 14h-16v-12h16zm-14-8h2v2h-2zm0 4h8v2h-8zm10 0h2v2h-2zm-6-4h8v2h-8z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Subtitles Off icon. */
export function IconSubtitlesOff(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <g fill="currentColor">
                <path d="m20.0001 4h-13.17002l2 2h11.17002v11.17l1.76 1.76c.15-.28.24-.59.24-.93v-12c0-1.1-.9-2-2-2z" />
                <path d="m18.0001 10h-5.17l2 2h3.17z" />
                <path d="m1.04004 3.86922 1.2 1.2c-.15.28-.24.59-.24.93v11.99998c0 1.1.9 2 2 2h13.16996l2.96 2.96 1.41-1.41-19.08996-19.09998zm2.96 2.96 3.17 3.17h-1.17v1.99998h2v-1.17l3.16996 3.17h-5.16996v2h7.16996l2 2h-11.16996z" />
            </g>
        </SvgIcon>
    )
}

/** Material Design Calculate icon. */
export function IconCalculate(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <g fill="currentColor">
                <path d="m19 3h-14c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2v-14c0-1.1-.9-2-2-2zm0 16h-14v-14h14z" />
                <path d="m11.25 7.7207h-5v1.5h5z" />
                <path d="m18 15.75h-5v1.5h5z" />
                <path d="m18 13.25h-5v1.5h5z" />
                <path d="m8 18h1.5v-2h2v-1.5h-2v-2h-1.5v2h-2v1.5h2z" />
                <path d="m14.09 10.95 1.41-1.41 1.41 1.41 1.06-1.06-1.41-1.42 1.41-1.41-1.06-1.06-1.41 1.41-1.41-1.41-1.06 1.06 1.41 1.41-1.41 1.42z" />
            </g>
        </SvgIcon>
    )
}

/** Material Design Subdirectory Arrow Right icon. */
export function IconSubdirectoryArrowRight(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path d="m19 15-6 6-1.42-1.42 3.59-3.58h-11.17v-12h2v10h9.17l-3.59-3.58 1.42-1.42z" fill="currentColor" />{' '}
        </SvgIcon>
    )
}

export function IconGroupedEvents(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                clipRule="evenodd"
                d="m2 6h2v14h14v2h-14c-1.1 0-2-.9-2-2zm6-4h12c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2h-12c-1.1 0-2-.9-2-2v-12c0-1.1.9-2 2-2zm0 14h12v-12h-12zm4.6851-3.6586-.5398 1.6584h-1.6477l2.5106-7.27275h1.9815l2.5071 7.27275h-1.6477l-.5398-1.6584zm1.2855-3.95242-.8949 2.75212h1.8466l-.8949-2.75212z"
                fill="currentColor"
                fillRule="evenodd"
            />
        </SvgIcon>
    )
}

/** Material Design Assistant Photo icon. */
export function IconFlag(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m12.36 6 .08.39.32 1.61h5.24v6h-3.36l-.08-.39-.32-1.61h-7.24v-6zm1.64-2h-9v17h2v-7h5.6l.4 2h7v-10h-5.6z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Bar Chart icon. */
export function IconBarChart(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path d="m5 9.2h3v9.8h-3zm5.6-4.2h2.8v14h-2.8zm5.6 8h2.8v6h-2.8z" fill="currentColor" />
        </SvgIcon>
    )
}

/** Material Design Bar Speed icon. */
export function IconGauge(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m19.5401 9.08537-1.1088 1.66773c.5347 1.0665.7965 2.249.7619 3.4415-.0346 1.1926-.3645 2.3579-.9602 3.3916h-12.49439c-.77421-1.3431-1.09502-2.8999-.91486-4.4397.18015-1.5397.85168-2.9804 1.91502-4.10853 1.06335-1.12809 2.4619-1.88351 3.98833-2.15426 1.5264-.27076 3.0995-.04243 4.486.65113l1.6677-1.10881c-1.698-1.08878-3.712-1.57666-5.72-1.38561-2.00792.19105-3.8938 1.04999-5.35594 2.43944-1.46213 1.38945-2.41605 3.22914-2.70916 5.22474-.2931 1.9956.09153 4.0319 1.09239 5.7831.15731.2725.3832.4991.65521.6572.27201.1582.58068.2424.89531.2443h12.48539c.3177.0012.63-.0815.9055-.2398.2754-.1583.5042-.3866.663-.6617.8306-1.4388 1.2474-3.0792 1.2045-4.74-.043-1.6608-.544-3.2774-1.4479-4.67135zm-8.8254 6.16603c.1675.1676.3663.3006.5852.3914.2189.0907.4535.1374.6904.1374s.4715-.0467.6904-.1374c.2189-.0908.4177-.2238.5852-.3914l5.1023-7.65346-7.6535 5.10236c-.1676.1674-.3006.3662-.3913.5851-.0908.2189-.1375.4535-.1375.6904 0 .237.0467.4716.1375.6905.0907.2188.2237.4177.3913.5851z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Extension icon. */
export function IconExtension(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m10.5 4.5c.28 0 .5.22.5.5v2h6v6h2c.28 0 .5.22.5.5s-.22.5-.5.5h-2v6h-2.12c-.68-1.75-2.39-3-4.38-3s-3.7 1.25-4.38 3h-2.12v-2.12c1.75-.68 3-2.39 3-4.38s-1.24-3.7-2.99-4.38l-.01-2.12h6v-2c0-.28.22-.5.5-.5zm0-2c-1.38 0-2.5 1.12-2.5 2.5h-4c-1.1 0-1.99.9-1.99 2v3.8h.29c1.49 0 2.7 1.21 2.7 2.7s-1.21 2.7-2.7 2.7h-.3v3.8c0 1.1.9 2 2 2h3.8v-.3c0-1.49 1.21-2.7 2.7-2.7s2.7 1.21 2.7 2.7v.3h3.8c1.1 0 2-.9 2-2v-4c1.38 0 2.5-1.12 2.5-2.5s-1.12-2.5-2.5-2.5v-4c0-1.1-.9-2-2-2h-4c0-1.38-1.12-2.5-2.5-2.5z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Groups icon. */
export function IconCohort(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m4 13c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm1.13 1.1c-.37-.06-.74-.1-1.13-.1-.99 0-1.93.21-2.78.58-.74.32-1.22 1.04-1.22 1.85v1.57h4.5v-1.61c0-.83.23-1.61.63-2.29zm14.87-1.1c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm4 3.43c0-.81-.48-1.53-1.22-1.85-.85-.37-1.79-.58-2.78-.58-.39 0-.76.04-1.13.1.4.68.63 1.46.63 2.29v1.61h4.5zm-7.76-2.78c-1.17-.52-2.61-.9-4.24-.9s-3.07.39-4.24.9c-1.08.48-1.76 1.56-1.76 2.74v1.61h12v-1.61c0-1.18-.68-2.26-1.76-2.74zm-8.17 2.35c.09-.23.13-.39.91-.69.97-.38 1.99-.56 3.02-.56s2.05.18 3.02.56c.77.3.81.46.91.69zm3.93-8c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm0-2c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Handyman icon. */
export function IconTools(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <g fill="currentColor">
                <path d="m21.67 18.17-5.3-5.3h-.99l-2.54 2.54v.99l5.3 5.3c.39.39 1.02.39 1.41 0l2.12-2.12c.39-.38.39-1.02 0-1.41zm-2.83 1.42-4.24-4.24.71-.71 4.24 4.24z" />
                <path d="m17.34 10.19 1.41-1.41 2.12 2.12c1.17-1.17 1.17-3.07 0-4.24l-3.54-3.54-1.41 1.41v-2.82l-.7-.71-3.54 3.54.71.71h2.83l-1.41 1.41 1.06 1.06-2.89 2.89-4.13-4.13v-1.42l-3.02-3.02-2.83 2.83 3.03 3.03h1.41l4.13 4.13-.85.85h-2.12l-5.3 5.3c-.39.39-.39 1.02 0 1.41l2.12 2.12c.39.39 1.02.39 1.41 0l5.3-5.3v-2.12l5.15-5.15zm-7.98 5.15-4.24 4.24-.71-.71 4.24-4.24z" />
            </g>
        </SvgIcon>
    )
}

/** Material Design Priority High icon. */
export function IconExclamation(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <g fill="currentColor">
                <path d="m12 21c1.1046 0 2-.8954 2-2s-.8954-2-2-2-2 .8954-2 2 .8954 2 2 2z" />
                <path d="m10 3h4v12h-4z" />
            </g>
        </SvgIcon>
    )
}
/** Material Design Push Pin icon. */
export function IconPin(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <g fill="currentColor">
                <path
                    d="M16,9V4l1,0c0.55,0,1-0.45,1-1v0c0-0.55-0.45-1-1-1H7C6.45,2,6,2.45,6,3v0 c0,0.55,0.45,1,1,1l1,0v5c0,1.66-1.34,3-3,3h0v2h5.97v7l1,1l1-1v-7H19v-2h0C17.34,12,16,10.66,16,9z"
                    fillRule="evenodd"
                />
            </g>
        </SvgIcon>
    )
}

/** Material Design Error Outline icon. */
export function IconErrorOutline(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m11 15h2v2h-2zm0-8h2v6h-2zm.99-5c-5.52 0-9.99 4.48-9.99 10s4.47 10 9.99 10c5.53 0 10.01-4.48 10.01-10s-4.48-10-10.01-10zm.01 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Warning Amber Outline icon. */
export function IconWarningAmber(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path d="m12 5.99 7.53 13.01h-15.06zm0-3.99-11 19h22zm1 14h-2v2h2zm0-6h-2v4h2z" fill="currentColor" />{' '}
        </SvgIcon>
    )
}

/** Material Design Comment icon. */
export function IconComment(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m20 4v13.17l-1.17-1.17h-14.83v-12zm0-2h-16c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14l4 4v-18c0-1.1-.9-2-2-2zm-2 10h-12v2h12zm0-3h-12v2h12zm0-3h-12v2h12z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Person Outlined icon. */
export function IconPerson(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m12 6c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2zm0 10c2.7 0 5.8 1.29 6 2h-12c.23-.72 3.31-2 6-2zm0-12c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm0 10c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Person Filled icon. */
export function IconPersonFilled(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" fill="currentColor" {...props}>
            <path d="M0 0h24v24H0z" fill="none" />
            <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
        </SvgIcon>
    )
}

/** Material Design Emoji People icon. */
export function IconEmojiPeople(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" fill="currentColor" {...props}>
            <circle cx="12" cy="4" r="2" />
            <path d="m15.89 8.11c-.39-.39-1.06-1.11-2.36-1.11-.21 0-1.42 0-2.54 0-2.75-.01-4.99-2.25-4.99-5h-2c0 3.16 2.11 5.84 5 6.71v13.29h2v-6h2v6h2v-11.95l3.95 3.95 1.41-1.41z" />
        </SvgIcon>
    )
}

/** Material Design Handyman icon. */
export function IconRecording(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m10 8v8l5-4zm9-5h-14c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2v-14c0-1.1-.9-2-2-2zm0 16h-14v-14h14z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Arrow Drop Down icon. */
export function IconArrowDropDown(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path d="m7 10 5 5 5-5z" fill="currentColor" />
        </SvgIcon>
    )
}

/** Material Design Article icon. */
export function IconArticle(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <g fill="currentColor">
                <path d="m19 5v14h-14v-14zm0-2h-14c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2v-14c0-1.1-.9-2-2-2z" />
                <path d="m14 17h-7v-2h7zm3-4h-10v-2h10zm0-4h-10v-2h10z" />
            </g>
        </SvgIcon>
    )
}

/** Material Design Question Answer icon. */
export function IconQuestionAnswer(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m15 4v7h-9.83l-1.17 1.17v-8.17zm1-2h-13c-.55 0-1 .45-1 1v14l4-4h10c.55 0 1-.45 1-1v-9c0-.55-.45-1-1-1zm5 4h-2v9h-13v2c0 .55.45 1 1 1h11l4 4v-15c0-.55-.45-1-1-1z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Help Outline icon. */
export function IconHelpOutline(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m11 18h2v-2h-2zm1-16c-5.52 0-10 4.48-10 10s4.48 10 10 10 10-4.48 10-10-4.48-10-10-10zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-14c-2.21 0-4 1.79-4 4h2c0-1.1.9-2 2-2s2 .9 2 2c0 2-3 1.75-3 5h2c0-2.25 3-2.5 3-5 0-2.21-1.79-4-4-4z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Info icon. */
export function IconInfo(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m11 7h2v2h-2zm0 4h2v6h-2zm1-9c-5.52 0-10 4.48-10 10s4.48 10 10 10 10-4.48 10-10-4.48-10-10-10zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Mail icon. */
export function IconMail(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m22 6c0-1.1-.9-2-2-2h-16c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2zm-2 0-8 5-8-5zm0 12h-16v-10l8 5 8-5z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconGithub(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                clipRule="evenodd"
                d="m12 2c-5.525 0-10 4.475-10 10 0 4.425 2.8625 8.1625 6.8375 9.4875.5.0875.6875-.2125.6875-.475 0-.2375-.0125-1.025-.0125-1.8625-2.5125.4625-3.1625-.6125-3.3625-1.175-.1125-.2875-.6-1.175-1.025-1.4125-.35-.1875-.85-.65-.0125-.6625.7875-.0125 1.35.725 1.5375 1.025.9 1.5125 2.3375 1.0875 2.9125.825.0875-.65.35-1.0875.6375-1.3375-2.225-.25-4.55-1.1125-4.55-4.9375 0-1.0875.3875-1.9875 1.025-2.6875-.1-.25-.45-1.275.1-2.65 0 0 .8375-.2625 2.75 1.025.8-.225 1.65-.3375 2.5-.3375s1.7.1125 2.5.3375c1.9125-1.3 2.75-1.025 2.75-1.025.55 1.375.2 2.4.1 2.65.6375.7 1.025 1.5875 1.025 2.6875 0 3.8375-2.3375 4.6875-4.5625 4.9375.3625.3125.675.9125.675 1.85 0 1.3375-.0125 2.4125-.0125 2.75 0 .2625.1875.575.6875.475 1.9852-.6702 3.7102-1.946 4.9323-3.648 1.2221-1.7019 1.8797-3.7442 1.8802-5.8395 0-5.525-4.475-10-10-10z"
                fill="currentColor"
                fillRule="evenodd"
            />
        </SvgIcon>
    )
}

/** Material Design Expand More icon. */
export function IconExpandMore(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path d="m16.59 8.59-4.59 4.58-4.59-4.58-1.41 1.41 6 6 6-6z" fill="currentColor" />
        </SvgIcon>
    )
}

/** Material Design More Horiz icon. */
export function IconEllipsis(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" height="24" viewBox="0 0 24 24" width="24" {...props}>
            <path
                d="m6 10c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm12 0c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm-6 0c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Content Copy icon. */
export function IconCopy(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m15.4545 3h-9.81814c-.9 0-1.63636.73636-1.63636 1.63636v11.45454h1.63636v-11.45454h9.81814zm2.4546 3.27273h-9.00001c-.9 0-1.63636.73636-1.63636 1.63636v11.45451c0 .9.73636 1.6364 1.63636 1.6364h9.00001c.9 0 1.6364-.7364 1.6364-1.6364v-11.45451c0-.9-.7364-1.63636-1.6364-1.63636zm0 13.09087h-9.00001v-11.45451h9.00001z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Open In New icon. */
export function IconOpenInNew(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m19 19h-14v-14h7v-2h-7c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2zm-5-16v2h3.59l-9.83 9.83 1.41 1.41 9.83-9.83v3.59h2v-7z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Receipt icon. */
export function IconBill(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <g fill="currentColor">
                <path d="m18.85 4.35-1.35-1.35-1.35 1.35-1.35-1.35-1.35 1.35-1.35-1.35-1.35 1.35-1.35-1.35-1.35 1.35-1.35-1.35v12.6h-2.7v2.7c0 1.494 1.206 2.7 2.7 2.7h10.8c1.494 0 2.7-1.206 2.7-2.7v-15.3zm-4.05 14.85h-8.1c-.495 0-.9-.405-.9-.9v-.9h9zm3.6-.9c0 .495-.405.9-.9.9s-.9-.405-.9-.9v-2.7h-8.1v-9.9h9.9z" />
                <path d="m14.8001 7.5h-5.39995v1.8h5.39995z" />
                <path d="m17.5001 7.5h-1.8v1.8h1.8z" />
                <path d="m14.8001 10.1996h-5.39995v1.8h5.39995z" />
                <path d="m17.5001 10.1996h-1.8v1.8h1.8z" />
            </g>
        </SvgIcon>
    )
}

/** Material Design Trending Flat icon. */
export function IconTrendingFlat(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path d="m20 12-4-4v3h-12v2h12v3z" fill="currentColor" />
        </SvgIcon>
    )
}

/** Material Design Trending Flat icon, rotated to indicate dropoff. This is different from Trending Down. */
export function IconTrendingFlatDown(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m17.6567 17.6558v-5.6568l-2.1214 2.1213-8.48523-8.48531-1.41422 1.41422 8.48525 8.48529-2.1213 2.1213z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Schedule (clock) icon. */
export function IconSchedule(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m11.992 4c-4.416 0-7.992 3.584-7.992 8s3.576 8 7.992 8c4.424 0 8.008-3.584 8.008-8s-3.584-8-8.008-8zm.008 14.4c-3.536 0-6.4-2.864-6.4-6.4s2.864-6.4 6.4-6.4 6.4 2.864 6.4 6.4-2.864 6.4-6.4 6.4zm.4-10.4h-1.2v4.8l4.2 2.52.6-.984-3.6-2.136z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

// saved insight menu 32x32 icons
interface InsightIconProps extends SvgIconProps {
    background?: string
    noBackground?: boolean
    children?: React.ReactNode
}

function InsightIcon({
    background = 'var(--muted-alt)',
    noBackground = false,
    children,
    ...props
}: InsightIconProps): JSX.Element {
    console.log(children, props)
    return (
        <SvgIcon viewBox="0 0 32 32" {...props}>
            {!noBackground ? <rect width="100%" height="100%" rx="4" fill={background} /> : null}
            {children}
        </SvgIcon>
    )
}

interface InsightIconInstanceProps extends Omit<InsightIconProps, 'children'> {
    color?: string
}
export function InsightsTrendsIcon({ color = 'white', ...props }: InsightIconInstanceProps): JSX.Element {
    return (
        <InsightIcon {...props}>
            <path
                d="M7.5 22.4898L13.5 16.4798L17.5 20.4798L26 10.9198L24.59 9.50977L17.5 17.4798L13.5 13.4798L6 20.9898L7.5 22.4898Z"
                fill={color}
            />
        </InsightIcon>
    )
}

export function InsightsFunnelsIcon({ color = 'white', ...props }: InsightIconInstanceProps): JSX.Element {
    return (
        <InsightIcon {...props}>
            <path
                d="M9 9.2002H12V23.0002H9V9.2002ZM14.6 13.0002H17.4V23.0002H14.6V13.0002ZM20.2 17.0002H23V23.0002H20.2V17.0002Z"
                fill={color}
            />
        </InsightIcon>
    )
}

export function InsightsRetentionIcon({ color = 'white', ...props }: InsightIconInstanceProps): JSX.Element {
    return (
        <InsightIcon {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M7.5 6.5C6.94772 6.5 6.5 6.94772 6.5 7.5V9.5C6.5 10.0523 6.94772 10.5 7.5 10.5H9.5C10.0523 10.5 10.5 10.0523 10.5 9.5V7.5C10.5 6.94772 10.0523 6.5 9.5 6.5H7.5ZM7.5 11.5C6.94772 11.5 6.5 11.9477 6.5 12.5V14.5C6.5 15.0523 6.94772 15.5 7.5 15.5H9.5C10.0523 15.5 10.5 15.0523 10.5 14.5V12.5C10.5 11.9477 10.0523 11.5 9.5 11.5H7.5ZM6.5 17.5C6.5 16.9477 6.94772 16.5 7.5 16.5H9.5C10.0523 16.5 10.5 16.9477 10.5 17.5V19.5C10.5 20.0523 10.0523 20.5 9.5 20.5H7.5C6.94772 20.5 6.5 20.0523 6.5 19.5V17.5ZM7.5 21.5C6.94772 21.5 6.5 21.9477 6.5 22.5V24.5C6.5 25.0523 6.94772 25.5 7.5 25.5H9.5C10.0523 25.5 10.5 25.0523 10.5 24.5V22.5C10.5 21.9477 10.0523 21.5 9.5 21.5H7.5ZM11.5 7.5C11.5 6.94772 11.9477 6.5 12.5 6.5H14.5C15.0523 6.5 15.5 6.94772 15.5 7.5V9.5C15.5 10.0523 15.0523 10.5 14.5 10.5H12.5C11.9477 10.5 11.5 10.0523 11.5 9.5V7.5ZM12.5 11.5C11.9477 11.5 11.5 11.9477 11.5 12.5V14.5C11.5 15.0523 11.9477 15.5 12.5 15.5H14.5C15.0523 15.5 15.5 15.0523 15.5 14.5V12.5C15.5 11.9477 15.0523 11.5 14.5 11.5H12.5ZM11.5 17.5C11.5 16.9477 11.9477 16.5 12.5 16.5H14.5C15.0523 16.5 15.5 16.9477 15.5 17.5V19.5C15.5 20.0523 15.0523 20.5 14.5 20.5H12.5C11.9477 20.5 11.5 20.0523 11.5 19.5V17.5ZM17.5 6.5C16.9477 6.5 16.5 6.94772 16.5 7.5V9.5C16.5 10.0523 16.9477 10.5 17.5 10.5H19.5C20.0523 10.5 20.5 10.0523 20.5 9.5V7.5C20.5 6.94772 20.0523 6.5 19.5 6.5H17.5ZM16.5 12.5C16.5 11.9477 16.9477 11.5 17.5 11.5H19.5C20.0523 11.5 20.5 11.9477 20.5 12.5V14.5C20.5 15.0523 20.0523 15.5 19.5 15.5H17.5C16.9477 15.5 16.5 15.0523 16.5 14.5V12.5ZM22.5 6.5C21.9477 6.5 21.5 6.94772 21.5 7.5V9.5C21.5 10.0523 21.9477 10.5 22.5 10.5H24.5C25.0523 10.5 25.5 10.0523 25.5 9.5V7.5C25.5 6.94772 25.0523 6.5 24.5 6.5H22.5Z"
                fill={color}
            />
        </InsightIcon>
    )
}

export function InsightsPathsIcon({ color = 'white', ...props }: InsightIconInstanceProps): JSX.Element {
    return (
        <InsightIcon {...props}>
            <path
                d="M13.5 9.5C14.6 9.5 15.5 8.6 15.5 7.5C15.5 6.4 14.6 5.5 13.5 5.5C12.4 5.5 11.5 6.4 11.5 7.5C11.5 8.6 12.4 9.5 13.5 9.5ZM9.75 12.9L7 27H9.1L10.85 19L13 21V27H15V19.45L12.95 17.4L13.55 14.4C14.85 16 16.8 17 19 17V15C17.15 15 15.55 14 14.65 12.55L13.7 10.95C13.35 10.35 12.7 10 12 10C11.75 10 11.5 10.05 11.25 10.15L6 12.3V17H8V13.65L9.75 12.9ZM17 6V13H20.75V27H22.25V13H26V6H17ZM22.01 12V10.25H18.5V8.75H22.01V7L24.5 9.5L22.01 12Z"
                fill={color}
            />
        </InsightIcon>
    )
}

export function InsightsStickinessIcon({ color = 'white', ...props }: InsightIconInstanceProps): JSX.Element {
    return (
        <InsightIcon {...props}>
            <path
                d="M8 22V21.35C8 21.01 8.16 20.69 8.41 20.54C10.1 19.53 12.03 19 14 19C14.03 19 14.05 19 14.08 19.01C14.18 18.31 14.38 17.64 14.67 17.03C14.45 17.01 14.23 17 14 17C11.58 17 9.32 17.67 7.39 18.82C6.51 19.34 6 20.32 6 21.35V24H15.26C14.84 23.4 14.51 22.72 14.29 22H8Z"
                fill={color}
            />
            <path
                d="M14 16C16.21 16 18 14.21 18 12C18 9.79 16.21 8 14 8C11.79 8 10 9.79 10 12C10 14.21 11.79 16 14 16ZM14 10C15.1 10 16 10.9 16 12C16 13.1 15.1 14 14 14C12.9 14 12 13.1 12 12C12 10.9 12.9 10 14 10Z"
                fill={color}
            />
            <path
                d="M22.9119 22.4229L23.8548 23.3657C24.9519 21.7029 24.7719 19.4314 23.3148 17.9657C22.4833 17.1429 21.4033 16.74 20.3148 16.7314L21.1376 15.9086L20.2291 15L17.8033 17.4257L20.2291 19.8514L21.1376 18.9429L20.2033 18.0086C20.2291 18.0086 20.2548 18 20.2805 18C21.0519 18 21.8148 18.2914 22.4062 18.8829C23.3662 19.8429 23.5205 21.2829 22.9119 22.4229Z"
                fill={color}
            />
            <path
                d="M20.3319 27L22.7576 24.5743L20.3319 22.1486L19.4233 23.0571L20.3491 23.9829C19.5519 24.0086 18.7548 23.7171 18.1548 23.1171C17.1948 22.1571 17.0405 20.7171 17.6491 19.5771L16.7062 18.6343C15.6091 20.2971 15.7891 22.56 17.2548 24.0257C18.0776 24.8486 19.1576 25.2686 20.2376 25.2771L19.4233 26.0914L20.3319 27Z"
                fill={color}
            />
        </InsightIcon>
    )
}

export function InsightsLifecycleIcon({ color = 'white', ...props }: InsightIconInstanceProps): JSX.Element {
    return (
        <InsightIcon {...props}>
            <path
                d="M10 14H13V24H10V14ZM10 9H13V13H10V9ZM20 20H23V24H20V20ZM20 17H23V19H20V17ZM15 17H18V24H15V17ZM15 13H18V16H15V13Z"
                fill={color}
            />
        </InsightIcon>
    )
}

export function IconPageview(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 18 18" {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M2 0H16C17.1 0 18 0.9 18 2V16C18 17.1 17.1 18 16 18H2C0.9 18 0 17.1 0 16V2C0 0.9 0.9 0 2 0ZM2 2V16H16V2H2ZM13.34 9C12.48 7.46 10.84 6.5 9 6.5C7.16 6.5 5.52 7.46 4.66 9C5.52 10.54 7.16 11.5 9 11.5C10.84 11.5 12.48 10.54 13.34 9ZM3 9C3.94 6.66 6.27 5 9 5C11.73 5 14.06 6.66 15 9C14.06 11.34 11.73 13 9 13C6.27 13 3.94 11.34 3 9ZM7.5 9C7.5 9.83 8.17 10.5 9 10.5C9.83 10.5 10.5 9.83 10.5 9C10.5 8.17 9.83 7.5 9 7.5C8.17 7.5 7.5 8.17 7.5 9Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconAutocapture(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 18 18" {...props}>
            <path
                d="M14.5 6L13.56 3.94L11.5 3L13.56 2.06L14.5 0L15.44 2.06L17.5 3L15.44 3.94L14.5 6Z"
                fill="currentColor"
            />
            <path
                d="M3 9.5L3.94 11.56L6 12.5L3.94 13.44L3 15.5L2.06 13.44L0 12.5L2.06 11.56L3 9.5Z"
                fill="currentColor"
            />
            <path d="M3 6L2.06 3.94L0 3L2.06 2.06L3 0L3.94 2.06L6 3L3.94 3.94L3 6Z" fill="currentColor" />
            <path
                d="M13.23 11.26L17 10L7 7L10 17L11.26 13.23L15.53 17.5L17.51 15.52L13.23 11.26Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconPageleave(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 18 18" {...props}>
            <path
                d="M7.09 12.59L8.5 14L13.5 9L8.5 4L7.09 5.41L9.67 8H0V10H9.67L7.09 12.59ZM16 0H2C0.89 0 0 0.9 0 2V6H2V2H16V16H2V12H0V16C0 17.1 0.89 18 2 18H16C17.1 18 18 17.1 18 16V2C18 0.9 17.1 0 16 0Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconAction(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 20 20" {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M0 4H2V18H16V20H2C0.9 20 0 19.1 0 18V4ZM6 0H18C19.1 0 20 0.9 20 2V14C20 15.1 19.1 16 18 16H6C4.9 16 4 15.1 4 14V2C4 0.9 4.9 0 6 0ZM6 14H18V2H6V14ZM10.6851 10.3414L10.1453 11.9998H8.49756L11.0082 4.72705H12.9897L15.4968 11.9998H13.8491L13.3093 10.3414H10.6851ZM11.9706 6.38898L11.0757 9.14111H12.9223L12.0274 6.38898H11.9706Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconEvent(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 20 10" {...props}>
            <path
                d="M7.4 10.6L2.8 6L7.4 1.4L6 0L0 6L6 12L7.4 10.6ZM12.6 10.6L17.2 6L12.6 1.4L14 0L20 6L14 12L12.6 10.6Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design light bulb icon. */
export function IconLightBulb(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                d="M12,2A7,7 0 0,0 5,9C5,11.38 6.19,13.47 8,14.74V17A1,1 0 0,0 9,18H15A1,1 0 0,0 16,17V14.74C17.81,13.47 19,11.38 19,9A7,7 0 0,0 12,2M9,21A1,1 0 0,0 10,22H14A1,1 0 0,0 15,21V20H9V21Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Close icon. */
export function IconClose(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Cancel icon. */
export function IconCancel(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m12 2c-5.53 0-10 4.47-10 10s4.47 10 10 10 10-4.47 10-10-4.47-10-10-10zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm3.59-13-3.59 3.59-3.59-3.59-1.41 1.41 3.59 3.59-3.59 3.59 1.41 1.41 3.59-3.59 3.59 3.59 1.41-1.41-3.59-3.59 3.59-3.59z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Delete (Trash) icon. */
export function IconDelete(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m16 9v10h-8v-10zm-1.5-6h-5l-1 1h-3.5v2h14v-2h-3.5zm3.5 4h-12v12c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Edit / Create / Mode icon. */
export function IconEdit(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m14.06 9.02.92.92-9.06 9.06h-.92v-.92zm3.6-6.02c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29zm-3.6 3.19-11.06 11.06v3.75h3.75l11.06-11.06z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Save icon. */
export function IconSave(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m17 3h-12c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-12zm2 16h-14v-14h11.17l2.83 2.83zm-7-7c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3zm-6-6h9v4h-9z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Lock icon. */
export function IconLock(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m18 8h-1v-2c0-2.76-2.24-5-5-5s-5 2.24-5 5v2h-1c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-10c0-1.1-.9-2-2-2zm-9-2c0-1.66 1.34-3 3-3s3 1.34 3 3v2h-6zm9 14h-12v-10h12zm-6-3c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}
/** Material Design Lock icon. */
export function IconLockLemon(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                d="M18 8H17V6C17 3.24 14.76 1 12 1C9.24 1 7 3.24 7 6V8H6C4.9 8 4 8.9 4 10V20C4 21.1 4.9 22 6 22H18C19.1 22 20 21.1 20 20V10C20 8.9 19.1 8 18 8ZM9 6C9 4.34 10.34 3 12 3C13.66 3 15 4.34 15 6V8H9V6ZM18 20H6V10H18V20ZM12 17C13.1 17 14 16.1 14 15C14 13.9 13.1 13 12 13C10.9 13 10 13.9 10 15C10 16.1 10.9 17 12 17Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Lock Open icon. */
export function IconLockOpen(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m18 8h-1v-2c0-2.76-2.24-5-5-5s-5 2.24-5 5h2c0-1.66 1.34-3 3-3s3 1.34 3 3v2h-9c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-10c0-1.1-.9-2-2-2zm0 12h-12v-10h12zm-6-3c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Delete Forever icon. */
export function IconDeleteForever(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m14.12 10.47-2.12 2.12-2.13-2.12-1.41 1.41 2.13 2.12-2.12 2.12 1.41 1.41 2.12-2.12 2.12 2.12 1.41-1.41-2.12-2.12 2.12-2.12zm1.38-6.47-1-1h-5l-1 1h-3.5v2h14v-2zm-9.5 15c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2v-12h-12zm2-10h8v10h-8z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Workspace Premium icon. */
export function IconPremium(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m9.68 13.69 2.32-1.76 2.31 1.76-.88-2.85 2.32-1.84h-2.84l-.91-2.81-.91 2.81h-2.84l2.31 1.84zm10.32-3.69c0-4.42-3.58-8-8-8s-8 3.58-8 8c0 2.03.76 3.87 2 5.28v7.72l6-2 6 2v-7.72c1.24-1.41 2-3.25 2-5.28zm-8-6c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6 2.69-6 6-6zm0 15-4 1.02v-3.1c1.18.68 2.54 1.08 4 1.08s2.82-.4 4-1.08v3.1z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Refresh icon. */
export function IconRefresh(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m17.65 6.35c-1.45-1.45-3.44-2.35-5.65-2.35-4.41999 0-7.98999 3.58-7.98999 8s3.57 8 7.98999 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.30999 0-5.99999-2.69-5.99999-6s2.69-6 5.99999-6c1.66 0 3.14.69 4.22 1.78l-3.22 3.22h7v-7z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Play icon. */
export function IconPlay(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path d="m10 8.64 5.27 3.36-5.27 3.36zm-2-3.64v14l11-7z" fill="currentColor" />{' '}
        </SvgIcon>
    )
}

/** Material Design Play icon. */
export function IconReplay(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon version="1.1" viewBox="0 0 24 24" {...props}>
            <path
                d="m12 5v-4l-5 5 5 5v-4c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6h-2c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"
                fill="currentColor"
            />{' '}
        </SvgIcon>
    )
}

/** Material Design Keyboard icon. */
export function IconKeyboard(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon height="1em" viewBox="0 0 24 24" width="1em" fill="currentColor" {...props}>
            <path d="M20 5H4c-1.1 0-1.99.9-1.99 2L2 17c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm-9 3h2v2h-2V8zm0 3h2v2h-2v-2zM8 8h2v2H8V8zm0 3h2v2H8v-2zm-1 2H5v-2h2v2zm0-3H5V8h2v2zm9 7H8v-2h8v2zm0-4h-2v-2h2v2zm0-3h-2V8h2v2zm3 3h-2v-2h2v2zm0-3h-2V8h2v2z" />
            <path d="M0 0h24v24H0zm0 0h24v24H0z" fill="none" />
        </SvgIcon>
    )
}

/** Material Design Search icon. */
export function IconMagnifier(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m15.5 14h-.79l-.28-.27c.98-1.14 1.57-2.62 1.57-4.23 0-3.59-2.91-6.5-6.5-6.5s-6.5 2.91-6.5 6.5 2.91 6.5 6.5 6.5c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99 1.49-1.49zm-6 0c-2.49 0-4.5-2.01-4.5-4.5s2.01-4.5 4.5-4.5 4.5 2.01 4.5 4.5-2.01 4.5-4.5 4.5z"
                fill="currentColor"
            />{' '}
        </SvgIcon>
    )
}

export function IconLegend(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="-3 -3 24 24" fill="none" {...props}>
            <path
                d="M8 4H14V6H8V4ZM8 8H14V10H8V8ZM8 12H14V14H8V12ZM4 4H6V6H4V4ZM4 8H6V10H4V8ZM4 12H6V14H4V12ZM17.1 0H0.9C0.4 0 0 0.4 0 0.9V17.1C0 17.5 0.4 18 0.9 18H17.1C17.5 18 18 17.5 18 17.1V0.9C18 0.4 17.5 0 17.1 0ZM16 16H2V2H16V16Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconExperiment(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon width="1em" height="1em" viewBox="-3 -4 24 24" fill="none" {...props}>
            <path
                d="M9.99999 7.33L15 14H2.99999L7.99999 7.33V2H9.99999V7.33ZM12.96 0H5.03999C4.61999 0 4.38999 0.48 4.64999 0.81L5.99999 2.5V6.67L0.199992 14.4C-0.290008 15.06 0.179992 16 0.999992 16H17C17.82 16 18.29 15.06 17.8 14.4L12 6.67V2.5L13.35 0.81C13.61 0.48 13.38 0 12.96 0Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconHeatmap(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon width="1em" height="1em" viewBox="0 0 32 32" {...props}>
            <path
                d="M17.5 1.49056C17.5 0.00305736 15.5844 -0.557568 14.7406 0.675557C7 11.9899 18 12.4993 18 17.9993C18 20.2262 16.1806 22.0281 13.9469 21.9987C11.7487 21.9706 10 20.1381 10 17.9399V12.5956C10 11.2393 8.34562 10.5812 7.41062 11.5643C5.7375 13.3218 4 16.3324 4 19.9993C4 26.6162 9.38312 31.9993 16 31.9993C22.6169 31.9993 28 26.6162 28 19.9993C28 9.35618 17.5 7.93681 17.5 1.49056V1.49056Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function UnverifiedEvent({ width = 24, height = 24, ...props }: React.SVGProps<SVGSVGElement>): JSX.Element {
    return (
        <SvgIcon width={width} height={height} viewBox="0 0 24 24" fill="none" {...props}>
            <path
                d="M4.8 17.4H19.2V15.6H4.8V17.4ZM6.6 21H17.4V19.2H6.6V21ZM19.2 13.8H4.8C3.81 13.8 3 12.99 3 12V4.8C3 3.81 3.81 3 4.8 3H19.2C20.19 3 21 3.81 21 4.8V12C21 12.99 20.19 13.8 19.2 13.8ZM19.2 4.8H4.8V12H19.2V4.8Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function VerifiedEvent({ width = 24, height = 24, ...props }: React.SVGProps<SVGSVGElement>): JSX.Element {
    return (
        <SvgIcon width={width} height={height} viewBox="0 0 24 24" fill="none" {...props}>
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
        </SvgIcon>
    )
}

export function ActionEvent({ width = 24, height = 24, ...props }: React.SVGProps<SVGSVGElement>): JSX.Element {
    return (
        <SvgIcon width={width} height={height} viewBox="0 0 24 24" fill="none" {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M14 3H4.8C3.81 3 3 3.81 3 4.8V12C3 12.99 3.81 13.8 4.8 13.8H19.2C20.19 13.8 21 12.99 21 12V11H19.2V12H4.8V4.8H14V3ZM19.2 17.4H4.8V15.6H19.2V17.4ZM17.4 21H6.6V19.2H17.4V21Z"
                fill="currentColor"
            />
            <path d="M19 8L20.37 7.37L21 6L21.63 7.37L23 8L21.63 8.63L21 10L20.37 8.63L19 8Z" fill="currentColor" />
            <path
                d="M18.94 3.94L18 6L17.06 3.94L15 3L17.06 2.06L18 0L18.94 2.06L21 3L18.94 3.94Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function CohortIcon({ width = 24, height = 12, ...props }: React.SVGProps<SVGSVGElement>): JSX.Element {
    return (
        <SvgIcon width={width} height={height} viewBox="0 0 24 12" fill="none" {...props}>
            <path
                d="M4 7C5.1 7 6 6.1 6 5C6 3.9 5.1 3 4 3C2.9 3 2 3.9 2 5C2 6.1 2.9 7 4 7ZM5.13 8.1C4.76 8.04 4.39 8 4 8C3.01 8 2.07 8.21 1.22 8.58C0.48 8.9 0 9.62 0 10.43V12H4.5V10.39C4.5 9.56 4.73 8.78 5.13 8.1ZM20 7C21.1 7 22 6.1 22 5C22 3.9 21.1 3 20 3C18.9 3 18 3.9 18 5C18 6.1 18.9 7 20 7ZM24 10.43C24 9.62 23.52 8.9 22.78 8.58C21.93 8.21 20.99 8 20 8C19.61 8 19.24 8.04 18.87 8.1C19.27 8.78 19.5 9.56 19.5 10.39V12H24V10.43ZM16.24 7.65C15.07 7.13 13.63 6.75 12 6.75C10.37 6.75 8.93 7.14 7.76 7.65C6.68 8.13 6 9.21 6 10.39V12H18V10.39C18 9.21 17.32 8.13 16.24 7.65ZM8.07 10C8.16 9.77 8.2 9.61 8.98 9.31C9.95 8.93 10.97 8.75 12 8.75C13.03 8.75 14.05 8.93 15.02 9.31C15.79 9.61 15.83 9.77 15.93 10H8.07ZM12 2C12.55 2 13 2.45 13 3C13 3.55 12.55 4 12 4C11.45 4 11 3.55 11 3C11 2.45 11.45 2 12 2ZM12 0C10.34 0 9 1.34 9 3C9 4.66 10.34 6 12 6C13.66 6 15 4.66 15 3C15 1.34 13.66 0 12 0Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function PropertyIcon({ width = 18, height = 10, ...props }: React.SVGProps<SVGSVGElement>): JSX.Element {
    return (
        <SvgIcon width={width} height={height} viewBox="0 0 18 10" fill="none" {...props}>
            <path
                d="M0 6H2V4H0V6ZM0 10H2V8H0V10ZM0 2H2V0H0V2ZM4 6H18V4H4V6ZM4 10H14V8H4V10ZM4 0V2H18V0H4ZM0 6H2V4H0V6ZM0 10H2V8H0V10ZM0 2H2V0H0V2ZM4 6H18V4H4V6ZM4 10H14V8H4V10ZM4 0V2H18V0H4Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function VerifiedPropertyIcon({
    width = 21,
    height = 16,
    ...props
}: React.SVGProps<SVGSVGElement>): JSX.Element {
    return (
        <SvgIcon width={width} height={height} viewBox="0 0 21 16" fill="none" {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M0 6H2V4H0V6ZM0 10H2V8H0V10ZM0 2H2V0H0V2ZM4 6H11H18V4H4V6ZM4 8H11V10H4V8ZM4 0V2H18V0H4ZM14.0628 11.5494L15.7289 13.2226L19.9372 9L21 10.07L15.7289 15.3555L13 12.6194L14.0628 11.5494Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Sensors icon. */
export function IconLive({ width = 24, height = 24, ...props }: React.SVGProps<SVGSVGElement>): JSX.Element {
    return (
        <SvgIcon width={width} height={height} viewBox="0 0 24 24" fill="none" {...props}>
            <path
                d="M8.184 16.179C7.203 15.207 6.6 13.857 6.6 12.363C6.6 10.869 7.203 9.519 8.184 8.547L9.462 9.825C8.805 10.473 8.4 11.373 8.4 12.363C8.4 13.353 8.805 14.253 9.453 14.91L8.184 16.179ZM15.816 16.179C16.797 15.207 17.4 13.857 17.4 12.363C17.4 10.869 16.797 9.519 15.816 8.547L14.538 9.825C15.195 10.473 15.6 11.373 15.6 12.363C15.6 13.353 15.195 14.253 14.547 14.91L15.816 16.179ZM12 10.563C11.01 10.563 10.2 11.373 10.2 12.363C10.2 13.353 11.01 14.163 12 14.163C12.99 14.163 13.8 13.353 13.8 12.363C13.8 11.373 12.99 10.563 12 10.563ZM19.2 12.363C19.2 14.352 18.39 16.152 17.085 17.448L18.363 18.726C19.992 17.097 21 14.847 21 12.363C21 9.879 19.992 7.629 18.363 6L17.085 7.278C18.39 8.574 19.2 10.374 19.2 12.363ZM6.915 7.278L5.637 6C4.008 7.629 3 9.879 3 12.363C3 14.847 4.008 17.097 5.637 18.726L6.915 17.448C5.61 16.152 4.8 14.352 4.8 12.363C4.8 10.374 5.61 8.574 6.915 7.278Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Cottage icon. */
export function IconCottage(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="m11.9 4.8 5.4 4.122v-1.422h1.8v2.799l2.7 2.061-1.089 1.431-1.611-1.233v8.442h-14.39995v-8.442l-1.611 1.224-1.089-1.422zm-5.39995 14.4h4.49995v-3.6h1.8v3.6h4.5v-8.01l-5.4-4.122-5.39995 4.122zm7.19995-16.2c0 1.494 1.206 2.7 2.7 2.7.495 0 .9.405.9.9h1.8c0-1.494-1.206-2.7-2.7-2.7-.495 0-.9-.405-.9-.9z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconCorporate(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <path
                d="M12 7V3H2V21H22V7H12ZM10 19H4V17H10V19ZM10 15H4V13H10V15ZM10 11H4V9H10V11ZM10 7H4V5H10V7ZM20 19H12V9H20V19ZM18 11H14V13H18V11ZM18 15H14V17H18V15Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Tune icon. */
export function IconTuning(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                fill="currentColor"
                d="M3,17V19H9V17H3M3,5V7H13V5H3M13,21V19H21V17H13V15H11V21H13M7,9V11H3V13H7V15H9V9H7M21,13V11H11V13H21M15,9H17V7H21V5H17V3H15V9Z"
            />
        </SvgIcon>
    )
}

/** Material Design Tray Arrow Down icon. */
export function IconExport(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                fill="currentColor"
                d="M2 12H4V17H20V12H22V17C22 18.11 21.11 19 20 19H4C2.9 19 2 18.11 2 17V12M12 15L17.55 9.54L16.13 8.13L13 11.25V2H11V11.25L7.88 8.13L6.46 9.55L12 15Z"
            />
        </SvgIcon>
    )
}

/** Material Design Filter List icon. */
export function IconFilter(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon width="1em" height="1em" viewBox="0 0 24 24" fill="none" {...props}>
            <path d="M10 18H14V16H10V18ZM3 6V8H21V6H3ZM6 13H18V11H6V13Z" fill="currentColor" />
        </SvgIcon>
    )
}

export function IconPlayCircle(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon fill="none" width="1em" height="1em" viewBox="0 0 20 20" {...props}>
            <path
                d="M9.99988 0C4.47988 0 -0.00012207 4.48 -0.00012207 10C-0.00012207 15.52 4.47988 20 9.99988 20C15.5199 20 19.9999 15.52 19.9999 10C19.9999 4.48 15.5199 0 9.99988 0ZM9.99988 18C5.58988 18 1.99988 14.41 1.99988 10C1.99988 5.59 5.58988 2 9.99988 2C14.4099 2 17.9999 5.59 17.9999 10C17.9999 14.41 14.4099 18 9.99988 18ZM7.49988 14.5L14.4999 10L7.49988 5.5V14.5Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconBookmarkBorder(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="-4 -3 24 24" {...props}>
            <path
                d="M12.5 0H2.5C1.4 0 0.5 0.9 0.5 2V18L7.5 15L14.5 18V2C14.5 0.9 13.6 0 12.5 0ZM12.5 15L7.5 12.82L2.5 15V2H12.5V15Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

/** Material Design Upload File icon. */
export function IconUploadFile(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                fill="currentColor"
                d="M14,2L20,8V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V4A2,2 0 0,1 6,2H14M18,20V9H13V4H6V20H18M12,12L16,16H13.5V19H10.5V16H8L12,12Z"
            />
        </SvgIcon>
    )
}

/** Material Design Check Circle Outline icon. */
export function IconCheckCircleOutline(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 48 48" {...props}>
            <path
                d="M24 0.666748C11.12 0.666748 0.666626 11.1201 0.666626 24.0001C0.666626 36.8801 11.12 47.3334 24 47.3334C36.88 47.3334 47.3333 36.8801 47.3333 24.0001C47.3333 11.1201 36.88 0.666748 24 0.666748ZM24 42.6668C13.71 42.6668 5.33329 34.2901 5.33329 24.0001C5.33329 13.7101 13.71 5.33342 24 5.33342C34.29 5.33342 42.6666 13.7101 42.6666 24.0001C42.6666 34.2901 34.29 42.6668 24 42.6668ZM34.71 13.6867L19.3333 29.0634L13.29 23.0434L9.99996 26.3334L19.3333 35.6668L38 17.0001L34.71 13.6867Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconApps(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="-4 -4 24 24" {...props}>
            <path
                d="M1.65 3.3C1.18333 3.3 0.791667 3.14167 0.475 2.825C0.158333 2.50833 0 2.11667 0 1.65C0 1.18333 0.158333 0.791667 0.475 0.475C0.791667 0.158333 1.18333 0 1.65 0C2.11667 0 2.50833 0.158333 2.825 0.475C3.14167 0.791667 3.3 1.18333 3.3 1.65C3.3 2.11667 3.14167 2.50833 2.825 2.825C2.50833 3.14167 2.11667 3.3 1.65 3.3ZM8 16C7.53333 16 7.14167 15.8417 6.825 15.525C6.50833 15.2083 6.35 14.8167 6.35 14.35C6.35 13.8833 6.50833 13.4917 6.825 13.175C7.14167 12.8583 7.53333 12.7 8 12.7C8.46667 12.7 8.85833 12.8583 9.175 13.175C9.49167 13.4917 9.65 13.8833 9.65 14.35C9.65 14.8167 9.49167 15.2083 9.175 15.525C8.85833 15.8417 8.46667 16 8 16ZM1.65 16C1.18333 16 0.791667 15.8417 0.475 15.525C0.158333 15.2083 0 14.8167 0 14.35C0 13.8833 0.158333 13.4917 0.475 13.175C0.791667 12.8583 1.18333 12.7 1.65 12.7C2.11667 12.7 2.50833 12.8583 2.825 13.175C3.14167 13.4917 3.3 13.8833 3.3 14.35C3.3 14.8167 3.14167 15.2083 2.825 15.525C2.50833 15.8417 2.11667 16 1.65 16ZM1.65 9.65C1.18333 9.65 0.791667 9.49167 0.475 9.175C0.158333 8.85833 0 8.46667 0 8C0 7.53333 0.158333 7.14167 0.475 6.825C0.791667 6.50833 1.18333 6.35 1.65 6.35C2.11667 6.35 2.50833 6.50833 2.825 6.825C3.14167 7.14167 3.3 7.53333 3.3 8C3.3 8.46667 3.14167 8.85833 2.825 9.175C2.50833 9.49167 2.11667 9.65 1.65 9.65ZM8 9.65C7.53333 9.65 7.14167 9.49167 6.825 9.175C6.50833 8.85833 6.35 8.46667 6.35 8C6.35 7.53333 6.50833 7.14167 6.825 6.825C7.14167 6.50833 7.53333 6.35 8 6.35C8.46667 6.35 8.85833 6.50833 9.175 6.825C9.49167 7.14167 9.65 7.53333 9.65 8C9.65 8.46667 9.49167 8.85833 9.175 9.175C8.85833 9.49167 8.46667 9.65 8 9.65ZM14.35 3.3C13.8833 3.3 13.4917 3.14167 13.175 2.825C12.8583 2.50833 12.7 2.11667 12.7 1.65C12.7 1.18333 12.8583 0.791667 13.175 0.475C13.4917 0.158333 13.8833 0 14.35 0C14.8167 0 15.2083 0.158333 15.525 0.475C15.8417 0.791667 16 1.18333 16 1.65C16 2.11667 15.8417 2.50833 15.525 2.825C15.2083 3.14167 14.8167 3.3 14.35 3.3ZM8 3.3C7.53333 3.3 7.14167 3.14167 6.825 2.825C6.50833 2.50833 6.35 2.11667 6.35 1.65C6.35 1.18333 6.50833 0.791667 6.825 0.475C7.14167 0.158333 7.53333 0 8 0C8.46667 0 8.85833 0.158333 9.175 0.475C9.49167 0.791667 9.65 1.18333 9.65 1.65C9.65 2.11667 9.49167 2.50833 9.175 2.825C8.85833 3.14167 8.46667 3.3 8 3.3ZM14.35 9.65C13.8833 9.65 13.4917 9.49167 13.175 9.175C12.8583 8.85833 12.7 8.46667 12.7 8C12.7 7.53333 12.8583 7.14167 13.175 6.825C13.4917 6.50833 13.8833 6.35 14.35 6.35C14.8167 6.35 15.2083 6.50833 15.525 6.825C15.8417 7.14167 16 7.53333 16 8C16 8.46667 15.8417 8.85833 15.525 9.175C15.2083 9.49167 14.8167 9.65 14.35 9.65ZM14.35 16C13.8833 16 13.4917 15.8417 13.175 15.525C12.8583 15.2083 12.7 14.8167 12.7 14.35C12.7 13.8833 12.8583 13.4917 13.175 13.175C13.4917 12.8583 13.8833 12.7 14.35 12.7C14.8167 12.7 15.2083 12.8583 15.525 13.175C15.8417 13.4917 16 13.8833 16 14.35C16 14.8167 15.8417 15.2083 15.525 15.525C15.2083 15.8417 14.8167 16 14.35 16Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconWebhook(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                d="M10 15H15.88C16.15 14.69 16.55 14.5 17 14.5C17.83 14.5 18.5 15.17 18.5 16C18.5 16.83 17.83 17.5 17 17.5C16.56 17.5 16.16 17.31 15.88 17H11.9C11.44 19.28 9.42 21 7 21C4.24 21 2 18.76 2 16C2 13.58 3.72 11.56 6 11.1V13.17C4.84 13.58 4 14.7 4 16C4 17.65 5.35 19 7 19C8.65 19 10 17.65 10 16V15ZM12.5 4C14.15 4 15.5 5.35 15.5 7H17.5C17.5 4.24 15.26 2 12.5 2C9.74 2 7.5 4.24 7.5 7C7.5 8.43 8.1 9.71 9.05 10.62L6.7 14.52C6.02 14.66 5.5 15.27 5.5 16C5.5 16.83 6.17 17.5 7 17.5C7.83 17.5 8.5 16.83 8.5 16C8.5 15.84 8.48 15.69 8.43 15.55L11.81 9.92C10.49 9.61 9.5 8.42 9.5 7C9.5 5.35 10.85 4 12.5 4ZM17 13C16.36 13 15.77 13.2 15.28 13.54L12.23 8.47C11.53 8.35 11 7.74 11 7C11 6.17 11.67 5.5 12.5 5.5C13.33 5.5 14 6.17 14 7C14 7.15 13.98 7.29 13.94 7.43L16.13 11.08C16.41 11.03 16.7 11 17 11C19.76 11 22 13.24 22 16C22 18.76 19.76 21 17 21C15.15 21 13.53 19.99 12.67 18.5H15.34C15.82 18.82 16.39 19 17 19C18.65 19 20 17.65 20 16C20 14.35 18.65 13 17 13Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconSlack(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon width="16" height="16" viewBox="0 0 2447.6 2452.5" {...props}>
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
        </SvgIcon>
    )
}

export function IconSlackExternal(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="-2 -2 24 24" {...props}>
            <g fill="currentColor" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.5">
                <path d="M13 4.75 18.25 10 13 15.25 7.75 10 13 4.75Z" />
                <path d="M8.01 5.76 7 4.75 1.75 10 7 15.25l1.01-1.01-2.872-3.037a1.75 1.75 0 0 1 0-2.406L8.01 5.76Z" />
            </g>
        </SvgIcon>
    )
}

export function IconGlobeLock(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M19.8912 5.45455H20.2418C20.6275 5.45455 20.9431 5.77013 20.9431 6.15584V9.66234C20.9431 10.0481 20.6275 10.3636 20.2418 10.3636H16.034C15.6483 10.3636 15.3327 10.0481 15.3327 9.66234V6.15584C15.3327 5.77013 15.6483 5.45455 16.034 5.45455H19.1899V4.75325C19.1899 4.17117 18.72 3.7013 18.1379 3.7013C17.5558 3.7013 17.086 4.17117 17.086 4.75325H16.3847C16.3847 3.78545 17.1701 3 18.1379 3C19.1057 3 19.8912 3.78545 19.8912 4.75325V5.45455ZM17.7873 12.8182C17.7873 12.54 17.7545 12.27 17.7218 12H19.3827C19.4073 12.27 19.4236 12.54 19.4236 12.8182C19.4236 17.3345 15.7582 21 11.2418 21C6.72545 21 3.06 17.3345 3.06 12.8182C3.06 8.30182 6.72545 4.63636 11.2418 4.63636C12.1009 4.63636 12.9191 4.76727 13.6964 5.01273V7.09091C13.6964 7.99091 12.96 8.72727 12.06 8.72727H10.4236V10.3636C10.4236 10.8136 10.0555 11.1818 9.60545 11.1818H7.96909V12.8182H12.8782C13.3282 12.8182 13.6964 13.1864 13.6964 13.6364V16.0909H14.5145C15.2509 16.0909 15.8564 16.5655 16.0691 17.2282C17.1327 16.0664 17.7873 14.52 17.7873 12.8182ZM4.69636 12.8182C4.69636 16.1564 7.19182 18.9055 10.4236 19.3064V17.7273C9.52363 17.7273 8.78727 16.9909 8.78727 16.0909V15.2727L4.86818 11.3536C4.76182 11.8282 4.69636 12.3109 4.69636 12.8182Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconLink(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                d="M7.90326 16.7536C6.93594 15.7863 6.93594 14.2137 7.90326 13.2464L10.166 10.9836L9.0912 9.90883L6.82846 12.1716C5.26717 13.7329 5.26717 16.2671 6.82846 17.8284C8.38975 19.3897 10.924 19.3897 12.4853 17.8284L14.7481 15.5657L13.6733 14.4909L11.4105 16.7536C10.4432 17.7209 8.87058 17.7209 7.90326 16.7536ZM10.7883 15L15.3137 10.4745L14.1824 9.34315L9.65688 13.8686L10.7883 15ZM12.4853 6.51472L10.2226 8.77746L11.2974 9.85226L13.5601 7.58952C14.5274 6.6222 16.1 6.6222 17.0674 7.58952C18.0347 8.55684 18.0347 10.1294 17.0674 11.0968L14.8046 13.3595L15.8794 14.4343L18.1422 12.1716C19.7035 10.6103 19.7035 8.07601 18.1422 6.51472C16.5809 4.95343 14.0466 4.95343 12.4853 6.51472Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconMessages(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="-2 -2 24 24" {...props}>
            <path
                d="M13 2V9H3.17L2 10.17V2H13ZM14 0H1C0.45 0 0 0.45 0 1V15L4 11H14C14.55 11 15 10.55 15 10V1C15 0.45 14.55 0 14 0ZM19 4H17V13H4V15C4 15.55 4.45 16 5 16H16L20 20V5C20 4.45 19.55 4 19 4Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}

export function IconCalendar(props: SvgIconProps): JSX.Element {
    return (
        <SvgIcon viewBox="0 0 24 24" {...props}>
            <path
                d="M19.2 3.8H18.3V2H16.5V3.8H7.5V2H5.7V3.8H4.8C3.81 3.8 3 4.61 3 5.6V20C3 20.99 3.81 21.8 4.8 21.8H19.2C20.19 21.8 21 20.99 21 20V5.6C21 4.61 20.19 3.8 19.2 3.8ZM19.2 20H4.8V10.1H19.2V20ZM19.2 8.3H4.8V5.6H19.2V8.3Z"
                fill="currentColor"
            />
        </SvgIcon>
    )
}
