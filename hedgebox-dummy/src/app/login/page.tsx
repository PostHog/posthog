'use client'

import Header from '@/components/Header'
import { useAuth } from '@/lib/auth'


import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

export default function LoginPage(): JSX.Element {
    const [formData, setFormData] = useState({
        email: '',
        password: '',
    })
    const [error, setError] = useState('')
    const { login, isLoading, user } = useAuth()
    const router = useRouter()

    useEffect(() => {
        if (user) {
            router.push('/files')
        }
    }, [user, router])

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
        const { name, value } = e.target
        setFormData((prev) => ({
            ...prev,
            [name]: value,
        }))
        setError('') // Clear error on input change
    }

    const handleSubmit = async (e: React.FormEvent): Promise<void> => {
        e.preventDefault()
        setError('')
        await login(formData.email, formData.password)
    }

    return (
        <div>
            <Header />

            <div className="min-h-screen bg-base-200 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
                <div className="max-w-md w-full">
                    <div className="card bg-base-100 shadow">
                        <div className="card-body">
                            <div className="text-center mb-6">
                                <h1 className="text-3xl font-bold">Welcome back!</h1>
                                <p className="text-base-content/70 mt-2">Sign into your hedgehog account</p>
                            </div>

                            {error && (
                                <div className="alert alert-error mb-4">
                                    <span>{error}</span>
                                </div>
                            )}

                            <form onSubmit={handleSubmit} className="space-y-6">
                                <div className="form-control">
                                    <label className="label">
                                        <span className="label-text font-medium">📧 Email address</span>
                                    </label>
                                    <input
                                        type="email"
                                        name="email"
                                        value={formData.email}
                                        onChange={handleInputChange}
                                        placeholder="hedgehog@example.com"
                                        className="input input-bordered w-full input-lg focus:ring-2 focus:ring-primary/20 transition-all"
                                        required
                                    />
                                </div>

                                <div className="form-control">
                                    <label className="label">
                                        <span className="label-text font-medium">🔒 Password</span>
                                    </label>
                                    <input
                                        type="password"
                                        name="password"
                                        value={formData.password}
                                        onChange={handleInputChange}
                                        placeholder="Enter your password"
                                        className="input input-bordered w-full input-lg focus:ring-2 focus:ring-primary/20 transition-all"
                                        required
                                    />
                                    <label className="label">
                                        <Link
                                            href="/forgot-password"
                                            className="label-text-alt link link-hover text-primary"
                                        >
                                            Forgot your password?
                                        </Link>
                                    </label>
                                </div>

                                <button
                                    type="submit"
                                    className="btn btn-primary w-full btn-lg hover:scale-105 transition-transform"
                                    disabled={isLoading}
                                >
                                    {isLoading ? 'Signing in...' : '🚀 Sign in'}
                                </button>
                            </form>

                            <div className="text-center mt-6">
                                <span className="text-base-content/70">Don't have an account? </span>
                                <Link href="/signup" className="link link-primary">
                                    Sign up
                                </Link>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
