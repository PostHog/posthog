static inline int apply_discount(int total, int bulk) {
    return bulk ? total - total / 10 : total;
}
