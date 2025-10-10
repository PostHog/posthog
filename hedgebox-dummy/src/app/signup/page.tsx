'use client'

import Header from '@/components/Header'
import { useAuth } from '@/lib/auth'


import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

export default function SignupPage(): JSX.Element {
    const [formData, setFormData] = useState({
        name: '',
        email: '',
        password: '',
        plan: 'personal/free',
    })
    const [error, setError] = useState('')
    const { signup, isLoading, user } = useAuth()
    const router = useRouter()

    useEffect(() => {
        if (user) {
            router.push('/files')
        }
    }, [user, router])

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>): void => {
        const { name, value } = e.target
        setFormData((prev) => ({
            ...prev,
            [name]: value,
        }))
    }

    const handleSubmit = async (e: React.FormEvent): Promise<void> => {
        e.preventDefault()
        setError('')
        await signup(formData.name, formData.email, formData.password, formData.plan)
    }

    return (
        <div>
            <Header />

            <div className="min-h-screen bg-base-200 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
                <div className="max-w-md w-full">
                    <div className="card bg-base-100 shadow-md">
                        <div className="card-body">
                            <div className="text-center mb-6">
                                <h1 className="text-3xl font-bold">Create your account</h1>
                                <p className="text-base-content/70 mt-2">
                                    Join thousands of hedgehogs sharing files securely
                                </p>
                            </div>

                            {error && (
                                <div className="alert alert-error mb-4">
                                    <span>{error}</span>
                                </div>
                            )}

                            <form onSubmit={handleSubmit} method="post" className="space-y-4">
                                <div className="form-control">
                                    <label className="label">
                                        <span className="label-text">Full name</span>
                                    </label>
                                    <input
                                        type="text"
                                        name="name"
                                        value={formData.name}
                                        onChange={handleInputChange}
                                        placeholder="Enter your hedgehog name"
                                        className="input input-bordered w-full"
                                        required
                                    />
                                </div>

                                <div className="form-control">
                                    <label className="label">
                                        <span className="label-text">Email address</span>
                                    </label>
                                    <input
                                        type="email"
                                        name="email"
                                        value={formData.email}
                                        onChange={handleInputChange}
                                        placeholder="hedgehog@example.com"
                                        className="input input-bordered w-full"
                                        required
                                    />
                                </div>

                                <div className="form-control">
                                    <label className="label">
                                        <span className="label-text">Password</span>
                                    </label>
                                    <input
                                        type="password"
                                        name="password"
                                        value={formData.password}
                                        onChange={handleInputChange}
                                        placeholder="Create a secure password"
                                        className="input input-bordered w-full"
                                        required
                                    />
                                </div>

                                <div className="form-control">
                                    <label className="label">
                                        <span className="label-text">Choose your plan</span>
                                    </label>
                                    <select
                                        name="plan"
                                        value={formData.plan}
                                        onChange={handleInputChange}
                                        className="select select-bordered w-full"
                                    >
                                        <option value="personal/free">Personal Free - $0/month</option>
                                        <option value="personal/pro">Personal Pro - $10/month</option>
                                        <option value="business/standard">Business Standard - $10/user/month</option>
                                        <option value="business/enterprise">
                                            Business Enterprise - $20/user/month
                                        </option>
                                    </select>
                                </div>

                                <div className="form-control">
                                    <label className="cursor-pointer label justify-start">
                                        <input type="checkbox" className="checkbox checkbox-primary mr-3" required />
                                        <span className="label-text text-sm">
                                            I agree to the{' '}
                                            <Link href="/terms" className="link link-primary">
                                                Terms of Service
                                            </Link>{' '}
                                            and{' '}
                                            <Link href="/privacy" className="link link-primary">
                                                Privacy Policy
                                            </Link>
                                        </span>
                                    </label>
                                </div>

                                <button
                                    type="submit"
                                    className={`btn btn-primary w-full ${isLoading ? 'loading' : ''}`}
                                    disabled={isLoading}
                                >
                                    {isLoading ? 'Creating Account...' : 'Create Account'}
                                </button>
                            </form>

                            <div className="text-center mt-6">
                                <span className="text-base-content/70">Already have an account? </span>
                                <Link href="/login" className="link link-primary">
                                    Sign in
                                </Link>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
