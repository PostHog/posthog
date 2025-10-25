'use client'

import Header from '@/components/Header'
import { pricingPlans } from '@/lib/data'
import Link from 'next/link'

export default function PricingPage(): React.JSX.Element {
    return (
        <div>
            <Header />

            <div className="bg-gray-50 py-16">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    {/* Header */}
                    <div className="text-center mb-16">
                        <h1 className="text-4xl font-bold text-gray-900 mb-4">Choose Your Hedgebox Plan</h1>
                        <p className="text-xl text-gray-600 max-w-3xl mx-auto">
                            Whether you're a solo hedgehog or running a full hedgehog business, we have the perfect plan
                            for your file sharing needs.
                        </p>
                    </div>

                    {/* Pricing Cards */}
                    <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-8">
                        {pricingPlans.map((plan, index) => (
                            <div
                                key={plan.name}
                                className={`card bg-base-100 shadow ${
                                    index === 1 ? 'ring-2 ring-primary ring-opacity-50 scale-105' : ''
                                }`}
                            >
                                <div className="card-body">
                                    {index === 1 && (
                                        <div className="badge badge-primary absolute -top-3 left-1/2 transform -translate-x-1/2">
                                            Most Popular
                                        </div>
                                    )}

                                    <div className="text-center">
                                        <h3 className="card-title justify-center text-xl mb-2">{plan.name}</h3>
                                        <div className="mb-4">
                                            <span className="text-4xl font-bold">{plan.price}</span>
                                            <span className="text-base-content/70 ml-1">/{plan.period}</span>
                                        </div>
                                        <div className="badge badge-secondary mb-6">{plan.storage}</div>
                                    </div>

                                    <ul className="space-y-3 mb-8">
                                        {plan.features.map((feature) => (
                                            <li key={feature} className="flex items-center">
                                                <svg
                                                    className="w-5 h-5 text-success mr-3"
                                                    fill="currentColor"
                                                    viewBox="0 0 20 20"
                                                >
                                                    <path
                                                        fillRule="evenodd"
                                                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                                                        clipRule="evenodd"
                                                    />
                                                </svg>
                                                <span>{feature}</span>
                                            </li>
                                        ))}
                                    </ul>

                                    <div className="card-actions justify-center">
                                        <Link
                                            href="/signup"
                                            className={`btn w-full ${index === 1 ? 'btn-primary' : 'btn-outline'}`}
                                        >
                                            {plan.price === '$0' ? 'Start Free' : 'Get Started'}
                                        </Link>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* FAQ Section */}
                    <div className="mt-20">
                        <div className="text-center mb-12">
                            <h2 className="text-3xl font-bold text-gray-900 mb-4">Frequently Asked Questions</h2>
                        </div>

                        <div className="max-w-4xl mx-auto">
                            <div className="grid md:grid-cols-2 gap-8">
                                <div>
                                    <h3 className="text-lg font-semibold text-gray-900 mb-2">
                                        Can I upgrade or downgrade anytime?
                                    </h3>
                                    <p className="text-gray-600">
                                        Yes! You can change your plan at any time. Upgrades take effect immediately,
                                        while downgrades take effect at the next billing cycle.
                                    </p>
                                </div>

                                <div>
                                    <h3 className="text-lg font-semibold text-gray-900 mb-2">Is my data safe?</h3>
                                    <p className="text-gray-600">
                                        Absolutely. We use enterprise-grade encryption and security measures to keep
                                        your files safe and secure.
                                    </p>
                                </div>

                                <div>
                                    <h3 className="text-lg font-semibold text-gray-900 mb-2">Do you offer refunds?</h3>
                                    <p className="text-gray-600">
                                        We offer a 30-day money-back guarantee on all paid plans. No questions asked!
                                    </p>
                                </div>

                                <div>
                                    <h3 className="text-lg font-semibold text-gray-900 mb-2">
                                        What file types are supported?
                                    </h3>
                                    <p className="text-gray-600">
                                        We support all file types! From documents and images to videos and archives - if
                                        hedgehogs need it, we support it.
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* CTA */}
                    <div className="mt-16 text-center">
                        <h2 className="text-2xl font-bold text-gray-900 mb-4">Still have questions?</h2>
                        <p className="text-gray-600 mb-6">
                            Our hedgehog support team is here to help you choose the right plan.
                        </p>
                        <Link href="/signup" className="btn btn-primary btn-lg">
                            Start Your Free Trial
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    )
}
