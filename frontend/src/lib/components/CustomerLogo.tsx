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
    <img className={`h-10 w-full bg-transparent px-3 py-3 ${className}`} src={src} alt={alt} />
)

export const CustomerLogo = ({ image, alt, className = '' }: CustomerProps): JSX.Element => {
    return (
        <li className="flex w-full items-center justify-center">
            <Logo className={className} src={image} alt={alt} />
        </li>
    )
}
