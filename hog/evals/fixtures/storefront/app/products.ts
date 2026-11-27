export interface Product {
    slug: string
    name: string
    price: number
}

export const PRODUCTS: Product[] = [
    { slug: 'trail-mug', name: 'Trail mug', price: 18 },
    { slug: 'canvas-tote', name: 'Canvas tote', price: 24 },
    { slug: 'wool-beanie', name: 'Wool beanie', price: 32 },
]
