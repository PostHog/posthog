package com.example.backend.model;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * apiHeatmapGetDTO
 */
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class apiHeatmapGetDTO {
    private int count;
    private int pointer_y;
    private float pointer_relative_x;
    private boolean pointer_target_fixed;
}
