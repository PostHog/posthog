import type { ReactNode } from 'react'

export const metadata = { title: 'Hedge Goods' }

export default function RootLayout({ children }: { children: ReactNode }) {
    return (
        <html lang="en">
            <body>
                <header>
                    <a href="/">Hedge Goods</a> · <a href="/signup">Create an account</a>
                </header>
                <main>{children}</main>
            </body>
        </html>
    )
}
