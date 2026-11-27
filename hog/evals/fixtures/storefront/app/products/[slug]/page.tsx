import { notFound } from 'next/navigation'

import { PRODUCTS } from '../../products'
import { AddToCart } from './add-to-cart'

export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
    const { slug } = await params
    const product = PRODUCTS.find((entry) => entry.slug === slug)
    if (!product) {
        notFound()
    }
    return (
        <article>
            <h1>{product.name}</h1>
            <p>${product.price}</p>
            <AddToCart slug={product.slug} />
        </article>
    )
}
