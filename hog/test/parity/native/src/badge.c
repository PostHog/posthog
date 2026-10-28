int badge_width(const char *label) {
    int width = 0;
    while (label[width] != 0) {
        width++;
    }
    return width * 7 + 12;
}
