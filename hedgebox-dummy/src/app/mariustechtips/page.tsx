'use client'

import Header from '@/components/Header'
import { posthog } from '@/lib/posthog'
import Link from 'next/link'
import { useEffect } from 'react'

export default function MariusTechTipsPage(): React.JSX.Element {
    useEffect(() => {
        if (typeof window !== 'undefined') {
            posthog.capture('$pageview', {
                $current_url: window.location.href,
                $host: window.location.host,
                $pathname: window.location.pathname,
                utm_source: new URLSearchParams(window.location.search).get('utm_source'),
            })
        }
    }, [])

    const handleProductAdClick = (adNumber: number, url: string): void => {
        posthog.capture('$autocapture', {
            $event_type: 'click',
            $external_click_url: url,
        })
    }

    return (
        <div>
            <Header />

            <div className="container mx-auto px-4 py-12 max-w-4xl">
                {/* Blog Header */}
                <div className="text-center mb-12">
                    <div className="avatar mb-4">
                        <div className="w-20 rounded-full">
                            <div className="bg-primary text-white text-2xl w-20 h-20 rounded-full flex items-center justify-center">
                                👨‍💻
                            </div>
                        </div>
                    </div>
                    <h1 className="text-4xl font-bold mb-2">Marius' Tech Tips</h1>
                    <p className="text-base-content/70 text-lg">Daily tips and tricks for tech-savvy hedgehogs</p>
                </div>

                {/* Featured Article */}
                <article className="card bg-base-100 shadow-md mb-8">
                    <div className="card-body">
                        <div className="badge badge-primary mb-4">Featured</div>
                        <h2 className="card-title text-3xl mb-4">
                            🔥 5 File Sharing Mistakes That Could Cost You Your Spikes
                        </h2>
                        <div className="text-base-content/70 mb-6">
                            <span>By Marius Hedgehog</span> • <span>December 15, 2024</span> • <span>5 min read</span>
                        </div>

                        <div className="prose max-w-none">
                            <p className="text-lg mb-4">
                                Hey fellow hedgehogs! 🦔 Today I'm sharing the most common file sharing mistakes I see
                                in the hedgehog community. These errors can lead to lost files, security breaches, and
                                even worse - detached spikes!
                            </p>

                            <h3 className="text-xl font-bold mb-3">1. Not Using Encrypted File Sharing</h3>
                            <p className="mb-4">
                                Many hedgehogs still share files through unencrypted channels. This is like rolling down
                                a hill without your protective spikes! Always ensure your file sharing platform uses
                                end-to-end encryption.
                            </p>

                            <div className="alert alert-info mb-6">
                                <svg
                                    xmlns="http://www.w3.org/2000/svg"
                                    fill="none"
                                    viewBox="0 0 24 24"
                                    className="stroke-current shrink-0 w-6 h-6"
                                >
                                    <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth="2"
                                        d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                                     />
                                </svg>
                                <div>
                                    <h4 className="font-bold">Pro Tip from Marius:</h4>
                                    <p>
                                        Look for platforms that offer military-grade encryption. Your files should be as
                                        protected as a hedgehog's vulnerable belly!
                                    </p>
                                </div>
                            </div>

                            <h3 className="text-xl font-bold mb-3">2. Sharing Files Without Access Controls</h3>
                            <p className="mb-4">
                                Setting proper permissions is crucial. You wouldn't let just any fox into your burrow,
                                so why give them access to your files? Always review who can view, edit, and share your
                                documents.
                            </p>

                            <h3 className="text-xl font-bold mb-3">3. Ignoring File Size Limits</h3>
                            <p className="mb-4">
                                Large files can slow down your entire workflow. Optimize your hedgehog photos and burrow
                                blueprints before sharing. Consider using compression or breaking large projects into
                                smaller chunks.
                            </p>

                            {/* Product Ads */}
                            <div className="bg-base-200 p-6 rounded-lg my-8">
                                <h4 className="font-bold mb-4 text-center">🎯 Sponsored Content</h4>
                                <div className="grid md:grid-cols-2 gap-4">
                                    <div className="card bg-base-100 shadow-sm">
                                        <div className="card-body">
                                            <h5 className="card-title text-lg">10ft Hedgehog Garden Statue</h5>
                                            <p className="text-sm">Show your hedgehog pride in your garden!</p>
                                            <div className="card-actions justify-end">
                                                <Link
                                                    href="https://shop.example.com/products/10ft-hedgehog-statue?utm_source=hedgebox&utm_medium=paid"
                                                    className="btn btn-primary btn-sm"
                                                    onClick={() =>
                                                        handleProductAdClick(
                                                            1,
                                                            'https://shop.example.com/products/10ft-hedgehog-statue?utm_source=hedgebox&utm_medium=paid'
                                                        )
                                                    }
                                                >
                                                    Shop Now
                                                </Link>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="card bg-base-100 shadow-sm">
                                        <div className="card-body">
                                            <h5 className="card-title text-lg">Hedge-Watching Cruise</h5>
                                            <p className="text-sm">Luxury cruise to observe hedgehogs in the wild!</p>
                                            <div className="card-actions justify-end">
                                                <Link
                                                    href="https://travel.example.com/cruise/hedge-watching?utm_source=hedgebox&utm_medium=paid"
                                                    className="btn btn-primary btn-sm"
                                                    onClick={() =>
                                                        handleProductAdClick(
                                                            2,
                                                            'https://travel.example.com/cruise/hedge-watching?utm_source=hedgebox&utm_medium=paid'
                                                        )
                                                    }
                                                >
                                                    Book Trip
                                                </Link>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <h3 className="text-xl font-bold mb-3">4. Not Backing Up Shared Files</h3>
                            <p className="mb-4">
                                Always keep copies of important files. Cloud storage is great, but having multiple
                                backups ensures you'll never lose those precious hedgehog family photos or important
                                burrow documentation.
                            </p>

                            <h3 className="text-xl font-bold mb-3">5. Using Weak Passwords</h3>
                            <p className="mb-4">
                                "hedgehog123" is NOT a secure password! Use complex passwords with a mix of letters,
                                numbers, and symbols. Consider using a password manager to keep track of all your
                                credentials.
                            </p>

                            <div className="alert alert-success mb-6">
                                <svg
                                    xmlns="http://www.w3.org/2000/svg"
                                    className="stroke-current shrink-0 h-6 w-6"
                                    fill="none"
                                    viewBox="0 0 24 24"
                                >
                                    <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth="2"
                                        d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                                    />
                                </svg>
                                <div>
                                    <h4 className="font-bold">Speaking of secure file sharing...</h4>
                                    <p>
                                        If you're looking for a platform that addresses all these concerns, check out{' '}
                                        <Link href="/" className="link link-primary font-semibold">
                                            Hedgebox
                                        </Link>
                                        . It's built specifically for hedgehogs who take their file security seriously!
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className="card-actions justify-between items-center mt-8">
                            <div className="flex gap-2">
                                <div className="badge badge-outline">File Sharing</div>
                                <div className="badge badge-outline">Security</div>
                                <div className="badge badge-outline">Tech Tips</div>
                            </div>
                            <div className="flex gap-2">
                                <button className="btn btn-circle btn-outline btn-sm">❤️</button>
                                <button className="btn btn-circle btn-outline btn-sm">📨</button>
                                <button className="btn btn-circle btn-outline btn-sm">🔗</button>
                            </div>
                        </div>
                    </div>
                </article>

                {/* CTA Section */}
                <div className="text-center bg-primary/10 p-8 rounded-lg">
                    <h3 className="text-2xl font-bold mb-4">Ready for Secure File Sharing?</h3>
                    <p className="text-base-content/70 mb-6">
                        Don't let these mistakes happen to you. Try Hedgebox today and keep your files as secure as your
                        spikes!
                    </p>
                    <div className="flex flex-col sm:flex-row gap-4 justify-center">
                        <Link href="/signup" className="btn btn-primary">
                            Start Free Trial
                        </Link>
                        <Link href="/pricing" className="btn btn-outline">
                            View Pricing
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    )
}
