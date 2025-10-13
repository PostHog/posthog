'use client'

import Header from '@/components/Header'
import { useAuth } from '@/lib/auth'
import Link from 'next/link'

export default function HomePage(): JSX.Element {
    const { user } = useAuth()

    return (
        <div className="min-h-screen bg-base-100">
            <Header />

            {/* Hero Section */}
            <section className="relative overflow-hidden bg-gradient-subtle">
                <div className="absolute inset-0 bg-grid-slate-100/50 [mask-image:linear-gradient(0deg,white,rgba(255,255,255,0.6))] dark:bg-grid-slate-700/25" />

                <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="pt-20 pb-16 text-center lg:pt-32">
                        {user ? (
                            <>
                                <div className="mb-8 flex items-center justify-center gap-2 animate-fade-in-up">
                                    <div className="inline-flex items-center rounded-full bg-base-200/80 px-3 py-1 text-sm font-medium mb-6 shadow-md">
                                        <span className="text-lg mr-2">👋</span>
                                        Welcome back, hedgehog!
                                    </div>
                                    <div className="avatar mb-6">
                                        <div className="w-8 h-8 rounded-full ring-1 ring-base-300 shadow-md">
                                            <img src={user.avatar} alt={user.name} />
                                        </div>
                                    </div>
                                </div>
                                <h1 className="text-4xl font-bold tracking-tight text-base-content sm:text-6xl lg:text-7xl mb-6">
                                    Welcome back, <span className="text-primary">{user.name.split(' ')[0]}</span>
                                    <span className="ml-2">🦔</span>
                                </h1>
                                <p className="text-xl text-base-content/70 mb-8 max-w-2xl mx-auto leading-relaxed">
                                    Ready to manage your files with hedgehog-level security and lightning-fast
                                    performance? Your digital spikes are waiting! ⚡
                                </p>
                                <div className="flex flex-col sm:flex-row gap-4 justify-center">
                                    <Link
                                        href="/files"
                                        className="btn btn-primary btn-lg px-8 rounded-xl transition-all"
                                    >
                                        📁 Go to files
                                    </Link>
                                    <Link
                                        href="/account/settings"
                                        className="btn btn-outline btn-lg px-8 rounded-xl transition-all"
                                    >
                                        ⚙️ Account settings
                                    </Link>
                                </div>
                            </>
                        ) : (
                            <>
                                <div className="mb-8 animate-fade-in-up">
                                    <div className="inline-flex items-center rounded-full bg-base-200/80 px-3 py-1 text-sm font-medium mb-8 shadow-md">
                                        <span className="text-lg mr-2">🍎</span>
                                        Now available in apple flavor!
                                    </div>
                                </div>
                                <h1 className="text-4xl font-bold tracking-tight text-base-content sm:text-6xl lg:text-7xl mb-6">
                                    File storage and sharing
                                    <br />
                                    <span className="text-primary">for hedgehogs</span>
                                </h1>
                                <p className="text-xl text-base-content/70 mb-8 max-w-3xl mx-auto leading-relaxed">
                                    Store, share, and collaborate on files with rock-solid security 🛡️, lightning-fast
                                    performance ⚡, and an intuitive interface designed for modern hedgehog families.
                                </p>
                                <div className="flex flex-col sm:flex-row gap-4 justify-center mb-12">
                                    <Link
                                        href="/signup"
                                        className="btn btn-primary btn-lg px-8 rounded-xl transition-all"
                                    >
                                        Get started free
                                    </Link>
                                    <Link
                                        href="/pricing"
                                        className="btn btn-outline btn-lg px-8 rounded-xl transition-all"
                                    >
                                        View pricing
                                    </Link>
                                </div>
                            </>
                        )}
                    </div>
                </div>
            </section>

            {/* Features Section */}
            <section className="py-8 bg-base-100">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="text-center mb-16">
                        <h2 className="text-3xl font-bold tracking-tight text-base-content sm:text-4xl mb-4">
                            Why hedgehogs choose Hedgebox
                        </h2>
                        <p className="text-lg text-base-content/70 max-w-2xl mx-auto">
                            Built specifically for the unique needs of hedgehog file management and collaboration.
                        </p>
                    </div>

                    <div className="grid lg:grid-cols-3 gap-8">
                        <div className="bg-base-100 border border-base-300/50 rounded-2xl p-8 shadow transition-all duration-300">
                            <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center mb-6">
                                <span className="text-3xl">🛡️</span>
                            </div>
                            <h3 className="text-xl font-semibold text-base-content mb-3">Fox-proof</h3>
                            <p className="text-base-content/70 leading-relaxed">
                                Our spike-based encryption keeps your files safe from crafty foxes. Share confidently
                                with granular controls.
                            </p>
                        </div>

                        <div className="bg-base-100 border border-base-300/50 rounded-2xl p-8 shadow transition-all duration-300">
                            <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center mb-6">
                                <span className="text-3xl">⚡</span>
                            </div>
                            <h3 className="text-xl font-semibold text-base-content mb-3">Instant</h3>
                            <p className="text-base-content/70 leading-relaxed">
                                Share and access files faster than you can roll down the hill. Your stuff is always just
                                a click away.
                            </p>
                        </div>

                        <div className="bg-base-100 border border-base-300/50 rounded-2xl p-8 shadow transition-all duration-300">
                            <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center mb-6">
                                <span className="text-3xl">🤝</span>
                            </div>
                            <h3 className="text-xl font-semibold text-base-content mb-3">Warm & fuzzy</h3>
                            <p className="text-base-content/70 leading-relaxed">
                                Real-time teamwork, notifications, and permissions—so your whole family can work
                                together.
                            </p>
                        </div>
                    </div>
                </div>
            </section>

            {/* CTA Section */}
            <section className="py-16 bg-base-200/50">
                <div className="max-w-4xl mx-auto text-center px-4 sm:px-6 lg:px-8">
                    <div className="mb-6">
                        <span className="text-6xl">🦔</span>
                    </div>
                    <h2 className="text-3xl font-bold tracking-tight text-base-content mb-4">
                        Ready to join the revolution?
                    </h2>
                    <p className="text-xl text-base-content/70 mb-8">
                        Join thousands of hedgehogs already using Hedgebox for their file sharing needs.
                    </p>
                    <Link href="/signup" className="btn btn-primary btn-lg px-8 rounded-xl transition-all">
                        🌟 Start your journey
                    </Link>
                </div>
            </section>

            {/* Footer */}
            <footer className="border-t border-base-300/50 py-12 bg-base-100">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex flex-col md:flex-row justify-between items-center">
                        <div className="w-7 h-7 bg-primary rounded-lg flex items-center justify-center group-hover:scale-105 transition-transform">
                            <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
                            </svg>
                        </div>
                        <p className="text-base-content/60 text-sm">
                            © 2024 Hedgebox. All rights reserved. Made with 🌵.
                        </p>
                    </div>
                </div>
            </footer>
        </div>
    )
}
