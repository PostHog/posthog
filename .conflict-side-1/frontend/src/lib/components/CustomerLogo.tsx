interface CustomerProps {
    image: string
    alt: string
    className?: string
}

interface LogoProps {
    src: string
    alt: string
    className?: string
}

const Logo = ({ src, alt, className = '' }: LogoProps): JSX.Element => (
    <img className={`bg-transparent w-full px-3 py-3 h-10 ${className}`} src={src} alt={alt} />
)

export const CustomerLogo = ({ image, alt, className = '' }: CustomerProps): JSX.Element => {
    return (
        <li className="flex items-center justify-center w-full">
            <Logo className={className} src={image} alt={alt} />
        </li>
    )
}
